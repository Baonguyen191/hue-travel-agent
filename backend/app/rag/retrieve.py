"""Hybrid place retrieval: BM25 on folded text + bge-m3 cosine, fused by reciprocal rank.

Filters come from the question and its ParsedQuery: categories named in the question, and an
anchor place after "gần" (POIs within ANCHOR_RADIUS_KM, nearest first, anchor removed). A linked
place without "gần" gets one extra ranking list so it comes first for single-place questions.
Without vectors or when the embed call fails, the retriever uses BM25 alone (mode "bm25").
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.rag.index import EmbedClient, EmbedError, EmbeddingStore, document_text
from app.schemas.place import Place
from app.services.poi_search import haversine_km, normalize_vietnamese
from app.services.preferences import map_preferences
from app.understanding.link import link_places
from app.understanding.models import ParsedQuery

logger = logging.getLogger(__name__)
RRF_K = 60
CANDIDATES = 50
ANCHOR_RADIUS_KM = 2.0
_TOKEN = re.compile(r"[a-z0-9]+")
_GAN_WORD = re.compile(r"\bgần\b", re.IGNORECASE)
# "chỗ" (place) folds to "cho" (market) in map_preferences; it is not a market word here.
_CHO_WORD = re.compile(r"\bchỗ\b", re.IGNORECASE)
_FOOD_QUESTION = re.compile(r"\b(an gi|an trua|an toi|an sang|quan an|cho an|an uong)\b")
_warned = False


def _warn_once(reason: str) -> None:
    global _warned
    if not _warned:
        logger.warning("Dense retrieval off, using BM25 only: %s", reason)
        _warned = True


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(normalize_vietnamese(text))


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(doc) for doc in docs]
        self.lengths = [len(doc) for doc in docs]
        self.avg_length = (sum(self.lengths) / len(docs)) if docs else 1.0
        df = Counter(token for doc in docs for token in set(doc))
        n = len(docs)
        self.idf = {token: math.log(1 + (n - count + 0.5) / (count + 0.5)) for token, count in df.items()}

    def scores(self, query: Sequence[str]) -> list[float]:
        terms = [token for token in set(query) if token in self.idf]
        out: list[float] = []
        for tf, length in zip(self.tf, self.lengths):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1.0))
            for token in terms:
                f = tf.get(token, 0)
                if f:
                    score += self.idf[token] * f * (self.k1 + 1) / (f + norm)
            out.append(score)
        return out


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, poi_id in enumerate(ranking, start=1):
            fused[poi_id] = fused.get(poi_id, 0.0) + 1.0 / (k + rank)
    return fused


@dataclass(frozen=True)
class Hit:
    poi_id: str
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None
    distance_km: float | None = None


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[Hit]
    mode: Literal["hybrid", "bm25"]
    anchor_name: str | None = None


class Retriever:
    """Loads every document once; `retrieve` only reads, so threads can share it."""

    def __init__(
        self,
        places: Sequence[Place],
        store: EmbeddingStore | None = None,
        client: EmbedClient | None = None,
    ) -> None:
        self.places = list(places)
        self.by_id = {place.id: place for place in self.places}
        self.bm25 = BM25([tokenize(document_text(place)) for place in self.places])
        self.client = client
        self.matrix: np.ndarray | None = None
        self.has_vector = np.zeros(len(self.places), dtype=bool)
        if store is not None and client is not None:
            ids, vectors = store.load(client.model)
            if not ids:
                _warn_once(f"no vectors for model {client.model}")
            else:
                row_of = {poi_id: row for row, poi_id in enumerate(ids)}
                matrix = np.zeros((len(self.places), vectors.shape[1]), dtype=np.float32)
                for index, place in enumerate(self.places):
                    if place.id in row_of:
                        matrix[index] = vectors[row_of[place.id]]
                        self.has_vector[index] = True
                self.matrix = matrix

    def retrieve(self, question: str, parsed: ParsedQuery | None = None, k: int = 5) -> RetrievalResult:
        anchor = self._anchor(question, parsed)
        allowed = self._allowed(question, parsed, anchor)
        rankings: list[list[str]] = []

        bm25_scores = self.bm25.scores(tokenize(question))
        bm25_order = sorted(
            (i for i in allowed if bm25_scores[i] > 0), key=lambda i: (-bm25_scores[i], self.places[i].id)
        )
        bm25_ids = [self.places[i].id for i in bm25_order[:CANDIDATES]]
        rankings.append(bm25_ids)

        dense_ids, mode = self._dense(question, allowed)
        rankings.append(dense_ids)

        distances: dict[str, float] = {}
        if anchor is not None:
            for i in allowed:
                place = self.places[i]
                distances[place.id] = haversine_km(anchor.lat, anchor.lon, place.lat, place.lon)
            rankings.append(sorted(distances, key=lambda poi_id: (distances[poi_id], poi_id))[:CANDIDATES])
        elif parsed is not None and parsed.place_query is not None and parsed.place_query.poi_id in self.by_id:
            rankings.append([parsed.place_query.poi_id])

        fused = rrf(rankings)
        ordered = sorted(fused, key=lambda poi_id: (-fused[poi_id], poi_id))[:k]
        bm25_rank = {poi_id: rank for rank, poi_id in enumerate(bm25_ids, start=1)}
        dense_rank = {poi_id: rank for rank, poi_id in enumerate(dense_ids, start=1)}
        hits = [
            Hit(
                poi_id=poi_id,
                score=round(fused[poi_id], 6),
                bm25_rank=bm25_rank.get(poi_id),
                dense_rank=dense_rank.get(poi_id),
                distance_km=round(distances[poi_id], 3) if poi_id in distances else None,
            )
            for poi_id in ordered
        ]
        return RetrievalResult(hits=hits, mode=mode, anchor_name=anchor.name if anchor is not None else None)

    def _anchor(self, question: str, parsed: ParsedQuery | None) -> Place | None:
        if " gan " not in f" {normalize_vietnamese(question)} ":
            return None
        matches = list(_GAN_WORD.finditer(question))
        if matches:
            tail = question[matches[-1].end() :].strip()
            if tail:
                linked = link_places([tail], self.places)
                if linked and linked[0].poi_id in self.by_id:
                    return self.by_id[linked[0].poi_id]
        if parsed is None or parsed.place_query is None or not parsed.place_query.poi_id:
            return None
        return self.by_id.get(parsed.place_query.poi_id)

    def _allowed(self, question: str, parsed: ParsedQuery | None, anchor: Place | None) -> list[int]:
        allowed = list(range(len(self.places)))
        if anchor is not None:
            allowed = [
                i
                for i in allowed
                if self.places[i].id != anchor.id
                and haversine_km(anchor.lat, anchor.lon, self.places[i].lat, self.places[i].lon) <= ANCHOR_RADIUS_KM
            ]
            # The anchor's own name words ("chùa", "lăng") name categories; they are not a filter.
            category_text = _CHO_WORD.sub(" ", question)
            categories, _ = map_preferences([category_text])
            own_categories, _ = map_preferences([anchor.name])
            categories = [
                category
                for category in categories
                if category not in own_categories and category != anchor.category
            ]
        else:
            category_text = question
            if parsed is not None and parsed.place_query is not None and parsed.place_query.text:
                category_text = re.sub(
                    re.escape(parsed.place_query.text), " ", category_text, flags=re.IGNORECASE
                )
            category_text = _CHO_WORD.sub(" ", category_text)
            categories, _ = map_preferences([category_text])
        if not categories and _FOOD_QUESTION.search(normalize_vietnamese(category_text)):
            categories = ["restaurant"]
        if categories:
            narrowed = [i for i in allowed if self.places[i].category in categories]
            if narrowed:
                allowed = narrowed
        return allowed

    def _dense(self, question: str, allowed: list[int]) -> tuple[list[str], Literal["hybrid", "bm25"]]:
        if self.matrix is None or self.client is None:
            return [], "bm25"
        candidates = [i for i in allowed if self.has_vector[i]]
        if not candidates:
            return [], "hybrid"
        try:
            vector = np.asarray(self.client.embed([question])[0], dtype=np.float32)
        except EmbedError as error:
            _warn_once(str(error))
            return [], "bm25"
        norm = float(np.linalg.norm(vector)) or 1.0
        rows = np.asarray(candidates)
        scores = self.matrix[rows] @ (vector / norm)
        order = np.argsort(-scores, kind="stable")[:CANDIDATES]
        return [self.places[int(rows[i])].id for i in order], "hybrid"
