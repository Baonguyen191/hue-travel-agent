# RAG for place questions + system metrics — design

Date: 2026-11-22. Branch: `feat/hue-multi-agent`. Local Ollama only
(`http://localhost:11434`): generator `qwen3.5:4b` (already pulled), judge `qwen3.5:9b`
(already pulled), embeddings `bge-m3` (to be pulled).

Goal: measure 13 metrics for the project in four groups (RAG, Multi-Agent, Travel
Planning, Performance). The project has no RAG today, so this design first adds a RAG
pipeline for open place questions in the chat, then adds one evaluation harness for all
13 metrics.

Context:
- The LLM is used only to extract `ParsedQuery` JSON (`app/understanding/extract.py`).
  `ChatService._place_info` (`app/chat/service.py`) answers with a template for one linked
  place (`texts.place_text`), plus a nearby list when the message contains "gần".
- Corpus: table `places` in `data/hue.sqlite`, 1587 rows (restaurant 826, cafe 285,
  historic 251, attraction 87, market 58, religious 57, park 15, museum 8). Text lives in
  `attributes_json`: type, address, opening hours, rating, price, phone, free flag,
  average visit minutes, and "Tóm tắt" (summary, only 373 rows).
- Existing understanding results (2026-11-22 rerun): rules test full match 0.38,
  qwen3.5:4b test full match 0.70, p50 2.4 s.

## Change to an earlier principle

The understanding design says "the LLM never writes facts or numbers shown to the user".
RAG answers are LLM text, so this design narrows that rule: **the LLM may write a place
answer only when every checkable fact in it matches the database.** The same fact checker
(section 2.3) runs in production before a reply is shown. If a check fails, the chat shows
the template answer for the top place instead. Plans, budgets, quotes and bookings stay
fully code-generated.

## 1. RAG pipeline (`backend/app/rag/`)

### 1.1 Index — `index.py`

- One document per POI, no chunking. `document_text(place)` joins, in this order: name,
  category label, type (theo nguồn), address, opening hours, price (or "miễn phí" for a
  free place), phone, rating, summary. Missing fields are skipped.
- Embeddings: `bge-m3` through Ollama `POST /api/embed`, batches of 32.
- Storage: a separate file `backend/data/rag_index.sqlite` (git-ignored, rebuilt by the command
  below), table `place_embeddings(poi_id TEXT PRIMARY KEY, model TEXT, text_hash TEXT,
  dim INTEGER, vector BLOB)`, float32 little endian. `index.py` creates the table with
  `CREATE TABLE IF NOT EXISTS`. Alembic is not used: it manages the plan store
  (`database_url()`), not the places data, and `data/hue.sqlite` stays read-only.
  Path from `rag_index_path()` in `app/core/config.py`.
- `python -m app.rag.index [--model bge-m3]` embeds only rows whose `text_hash`
  (sha256 of the document text) or model changed, and deletes rows for POIs that no
  longer exist. It prints counts: embedded, unchanged, deleted.
- Config: `RAG_EMBED_MODEL` (default `bge-m3`), `RAG_GEN_MODEL` (default the
  `qu_model()` value), `RAG_ENABLED` (default true), in `app/core/config.py`.

### 1.2 Retriever — `retrieve.py`

- `Retriever(places, embeddings, embed_client | None)`. Loads all documents and vectors
  into memory once (1587 × 1024 float32 ≈ 6.5 MB).
- BM25 (Okapi, k1=1.5, b=0.75, written in the module, no new dependency) over
  `normalize_vietnamese(document_text)` tokens.
- Dense: cosine between the query embedding and all vectors (numpy; `numpy>=1.26,<3` is
  added to `backend/requirements.txt`, the only new dependency).
- Fusion: reciprocal rank fusion, `score = Σ 1 / (60 + rank)` over the BM25 and dense
  top-50 lists.
- Filters from `ParsedQuery`, applied before fusion:
  - categories, when the query names one (reuse `map_preferences` on the question);
  - anchor: if the question contains "gần" and a place after it links (the existing
    `link.py` rule from commit 392fbec), keep POIs within 2 km of the anchor and add
    `1 / (60 + distance_rank)` as a third RRF list. The anchor itself is removed from
    the results;
  - linked place without "gần": a one-item RRF list with that POI, so a single-place
    question ranks its place first.
- `retrieve(question, parsed, k=5) -> RetrievalResult {hits: [ {poi_id, score,
  bm25_rank, dense_rank, distance_km} ], mode: "hybrid" | "bm25"}`.
- When the embedding table is empty, `bge-m3` is missing, or the embed call fails:
  `mode="bm25"`, one logged warning per process.

### 1.3 Generator — `answer.py`

- `RagAnswerer(ollama_url, model, transport=None)`. Same HTTP style as
  `OllamaExtractor`: `/api/chat`, `format` = JSON schema, `stream` false, `think` false,
  temperature 0.
- Context block: for each hit, `[poi_id] document_text`. Prompt (Vietnamese): answer only
  from the context; put `[poi_id]` after each sentence that uses a place; if the context
  does not answer the question, say so in one sentence and cite nothing.
- Output schema: `{answer: str, cited_poi_ids: [str], answerable: bool}`.
- Post-processing: cited ids not in the context are dropped; `answerable=true` with no
  cited ids becomes a refusal.
- Then the fact checker (2.3) runs. On a mismatch: `source="fallback"`.
- Errors (timeout, invalid JSON): retry once, then fall back to the template answer for
  hit 1 (`source="fallback"`, `error` set). Empty retrieval: fixed refusal text, no LLM
  call.
- Returns `RagAnswer {text, cited_poi_ids, answerable, source: "llm" | "fallback" |
  "refusal", retrieval: RetrievalResult, usage: Usage, error: str | None}`.

### 1.4 Chat wiring

- `ChatService._place_info` calls `RagAnswerer` for every `place_info` turn, also when no
  place was linked. Cards: `place_card` for each cited POI, in citation order (at most 3).
- When `RAG_ENABLED` is false or the answerer is not configured, the current template
  path runs unchanged. Every existing chat test must still pass.
- `api/chat.py` builds the retriever once at startup next to the extractor.

### 1.5 Token usage — `app/core/usage.py`

- `Usage {prompt_tokens, completion_tokens, calls}` with addition.
- `UsageRecorder`: a context-local collector. `OllamaExtractor` and `RagAnswerer` add
  `prompt_eval_count` and `eval_count` from each Ollama response; absent counts add 0.
  Embedding calls add `prompt_eval_count` only when Ollama returns it.
- `UsageRecorder` uses a `contextvars.ContextVar`, so callers do not pass it through.
  The evaluator opens a recorder around each `ChatService.handle` call and reads it
  afterwards. `ChatReply` and the API do not change.

## 2. Metrics

### 2.1 Gold sets (`data/eval/`)

- `rag_eval_v1.jsonl`, 60 items, dev 40 / test 20. Fields: `id`, `split`, `group`
  (`single_place` 15, `near_place` 15, `by_category` 15, `unanswerable` 15), `question`,
  `relevant_poi_ids` (set), `reference_answer`.
  - Gold POIs come from structured SQL (exact name, category plus distance from an
    anchor, attribute filters), never from the retriever. `near_place` gold is every POI
    of the asked category within 1 km of the anchor; `by_category` gold is every POI
    that matches the filter. Both can hold dozens of ids.
  - `unanswerable`: hotel questions, places outside Huế, facts the DB lacks (e.g. Wi-Fi);
    `relevant_poi_ids` empty.
- `scenarios_v1.jsonl`, 40 multi-turn chat scenarios, dev 25 / test 15. Each has `turns`
  (user texts) and `expect`:
  - `handlers`: one handler name per turn (`plan_new`, `modify`, `place_info`,
    `ask_approve`, `ask_book`, `out_of_scope`, `confirm_defaults`, `run_approve`,
    `run_book`, `cancel`). A clarification question is `plan_new` with final state
    `clarifying`;
  - `final_state`: `awaiting_approval | approved | booked | answered | clarifying |
    confirming | refused | failed` (`confirming` = the bot asked to confirm an approval or
    a booking);
  - `trace`: expected orchestrator node list for each plan run, including retries;
  - `tools_called` and `tools_not_called` (from `transport`, `hotel`, `booking`,
    `poi_search`, `rag`);
  - `budget`: `{budget_vnd, feasible: bool}` when the scenario sets a budget;
  - `constraints`: `{must_include, exclude, exclude_categories, categories, num_days,
    start_date}` when the scenario sets them.
  Sentences are reused from `query_eval_v2.jsonl` where possible, plus variants with a
  budget, a trip starting in Huế, a plan change, approval and booking.
- Claude drafts both files; the user reviews a random sample of about 15 items before
  any run. Reference date stays `EVAL_REF = 2026-11-18`.

### 2.2 RAG metrics (on `rag_eval_v1`, K = 5)

- **Context Precision**: `Σ_k (P@k · rel_k) / |relevant ∩ top-K|` over the retrieved ids
  (RAGAS form, id-based, no LLM). 0 when nothing relevant is retrieved. Items with empty
  gold are skipped.
- **Context Recall**: `|relevant ∩ top-K| / min(|relevant|, K)`. The `min` keeps the
  score reachable when the gold set is larger than K (near_place and by_category);
  for gold sets of size ≤ K this is the usual recall. Items with empty gold are skipped.
- **Faithfulness**: supported claims / all claims in the answer.
  - The judge (`qwen3.5:9b`) splits the answer into atomic claims, then labels each claim
    supported or not supported by the retrieved context.
  - The fact checker overrides the judge: a claim that states opening hours, a price, a
    phone number or an address of a cited POI is not supported if the value differs from
    the DB.
  - Refusals with no claims score 1.0 and are counted separately.
- **Answer Correctness**: claim F1 against `reference_answer`. The judge labels TP
  (claim in both), FP (answer only), FN (reference only); `F1 = TP / (TP + 0.5 (FP + FN))`.
  Reported next to `citation_hit = cited ∩ relevant ≠ ∅`. For `unanswerable` items, the
  score is 1 when the bot refuses and 0 otherwise.
- Also reported: refusal precision and recall, `mode` counts (hybrid or bm25), fallback
  count, and each metric per group.

### 2.3 Fact checker — `app/rag/facts.py`

Shared by the generator (production) and the evaluator. For each cited POI, find in the
answer: clock times (`HH:MM`, `HHhMM`; durations such as "2 giờ" are not checked, to avoid
false alarms), prices with a unit (`50.000đ`, `50k`, `50 nghìn`), phone numbers, and the
text after "địa chỉ". A fact is checked against the POIs cited in the same sentence. Each found value must match the cited POI's DB value
(times inside the opening window string, prices inside `[price_min, price_max]`, phone
digits equal, address token overlap ≥ 0.6). Returns a list of mismatches.

### 2.4 Multi-Agent metrics (on `scenarios_v1`)

- The runner drives `ChatService` with an in-memory store and the mock providers. Each
  provider and the retriever are wrapped in a spy that records calls. Handler names come
  from a hook in `ChatService._dispatch` (records the method name; no behaviour change).
- **Task Success Rate**: share of scenarios whose final state equals `final_state` and
  whose turns raised no exception.
- **Routing Accuracy**: (a) per turn: handler equals the gold handler; (b) per plan run:
  the orchestrator `trace` equals the gold `trace`. Both reported; the headline number
  is (a).
- **Tool Correctness**: per scenario, exact when the set of called tools contains every
  `tools_called` entry and no `tools_not_called` entry. Also tool-level precision and
  recall over all scenarios.

### 2.5 Travel Planning metrics (every plan the scenarios produce)

- **Budget Compliance Rate**: over scenarios with a budget, on the final plan. The budget
  result has no "recommended" option, so: when gold says the budget is feasible, pass when
  at least one option has `known_total_max_vnd ≤ budget_vnd` and no option labelled
  `WITHIN_BUDGET` exceeds it; when gold says it is not feasible, pass when the result
  reports `shortfall_vnd` and no option claims a `WITHIN_*` status.
- **Schedule Feasibility Rate**: pass when `validate_itinerary` is valid, every VISIT
  lies inside its POI's opening window (`parse_simple_opening_window`; POIs without a
  parsable window are not checked and are counted), and no event ends after 21:00
  (`ItineraryConfig` has no day-end field; dinner starts from 18:00 and lasts 75 minutes).
- **Constraint Satisfaction Rate**: pass when all of these hold: every `must_include`
  POI is scheduled; no `exclude` POI and no `exclude_categories` category appears as a
  visit, meal or cafe; number of days and start date equal the gold; each requested
  category appears at least once. Also reported per constraint type.

### 2.6 Performance

- **End-to-End Latency**: wall time of `ChatService.handle` per turn, with the LLM on,
  turns run one after another (no concurrency). p50, p95 and mean, overall and per
  handler, on the scenario suite. On the RAG suite, latency is the time of understanding
  plus `RagAnswerer.answer` for the question (the same work a `place_info` turn does).
  The RAG suite calls understanding and the answerer directly, so RAG metrics do not
  depend on routing; routing is measured on the scenario suite.
- **Average Token Usage**: mean prompt, completion and total tokens per turn, split into
  extractor and RAG generator. Judge tokens and embedding tokens are reported separately
  and are not part of the headline.

### 2.7 Runner and reports — `backend/app/evaluation/`

- Modules: `gold.py` (models and loading), `rag_metrics.py`, `agent_metrics.py`,
  `planning_metrics.py`, `judge.py` (9b claim split and labels), `spies.py`, `run.py`.
- `python -m app.evaluation.run --suite rag|agents|all --split dev|test|all
  [--judge-model qwen3.5:9b] [--no-llm]` writes
  `reports/system/<suite>_<split>.json` with per-item records and a summary.
- `reports/system/README.md`: one table with the 13 metrics (dev and test), the run
  configuration, and 10 failure examples with causes.
- Protocol: one tuning round on dev only, then test once, as in the understanding report.

## 3. Error handling

- Index missing or `bge-m3` missing: BM25 only, `mode="bm25"` in every record.
- Generator failure: retry once, then template fallback (`source="fallback"`).
- Judge failure or invalid JSON: retry once, then `judge_error` on that item; the item
  leaves the denominator, and the report states how many items left.
- Exception in a scenario turn: that turn records `error`, the scenario fails, the run
  continues.
- Ollama down: the `rag` suite stops at start with a clear message; the `agents` suite
  runs with the rules fallback and the report records `extractor: "rules"`.

## 4. Testing

pytest, no real Ollama calls (`httpx.MockTransport`, as in
`tests/test_understanding_extract.py`):

- `test_usage.py`: recorder sums counts; absent counts add 0.
- `test_rag_index.py`: document text order and skips, hash, re-embed only changed rows,
  delete removed rows, float32 BLOB round trip, table created in a temporary file.
- `test_rag_retrieve.py`: BM25 with and without diacritics, RRF on fixed rankings,
  category filter, anchor radius and anchor removal, BM25-only mode.
- `test_rag_facts.py`: time, price, phone and address matches and mismatches.
- `test_rag_answer.py`: JSON parse, dropping ids outside the context, refusal on empty
  retrieval, retry then fallback, fact mismatch to fallback.
- `test_chat_service.py`: `place_info` through RAG; template path when RAG is disabled or
  fails. Existing chat tests unchanged.
- `test_eval_rag_metrics.py`: precision and recall on hand-computed rankings;
  faithfulness and correctness with a fake judge; fact override.
- `test_eval_agent_metrics.py`: routing, tool spies, budget, feasibility and constraint
  checks on hand-built plans.
- `test_eval_run.py`: runner on two items per suite with a fake judge; output JSON
  schema.

The full suite (587 tests today) must pass after every step.

## 5. Build order (one commit per step, tests in the same step)

1. `Usage`, `UsageRecorder`, token capture in `OllamaExtractor`.
2. `app/rag/index.py` and `rag_index_path()`; ignore `data/rag_index.sqlite` in git;
   pull `bge-m3`; build the index.
3. `app/rag/retrieve.py`.
4. `app/rag/facts.py`, `app/rag/answer.py`.
5. Chat wiring in `ChatService._place_info` and `api/chat.py`.
6. Gold files `rag_eval_v1.jsonl`, `scenarios_v1.jsonl`; user reviews a sample.
7. `app/evaluation/` modules and runner.
8. Dev run, one tuning round on dev, one test run, `reports/system/README.md`.

Implementation: Claude (Opus) writes one brief per step; a `haiku` subagent writes the
code; Opus reviews the diff and runs the tests before accepting.

## 6. Out of scope

Vector database, cross-encoder reranking, chunking, new UI beyond the existing place
cards, model fine-tuning, RAGAS or LangChain dependencies, hotel questions through RAG.
