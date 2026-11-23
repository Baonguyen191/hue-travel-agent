"""Build backend/app/data/guide_corpus.json from Vietnamese Wikipedia lead sections.

Two steps, run once with network access:

1. `--propose`: for the heritage/attraction POIs (historic, religious, attraction, museum, park) plus the
   30 highest-rated other POIs, search Vietnamese Wikipedia for "<name> Huế" and write the candidate titles
   to backend/scripts/guide_proposals.json. This file is a working aid and is git-ignored.
2. Default: for the titles curated by hand in `PLACE_ARTICLES`, fetch the lead section (plain text), the
   article URL and the history URL, plus the full plain extract to pick up to three short sections
   (see `split_sections`), and write backend/app/data/guide_corpus.json.

Curation rule: keep a POI only when the article is clearly about that exact place (title equal to the place
name or a well-known alias). Generic pages (a city, a person, a different place with the same name) are
rejected by hand.

Run: .venv/Scripts/python.exe backend/scripts/build_guide_corpus.py [--propose]
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, for the sentence splitter
from app.services.guide import split_sentences  # noqa: E402

API = "https://vi.wikipedia.org/w/api.php"
USER_AGENT = "HueTravelAgent/0.1 (https://www.mediawiki.org/wiki/API:Etiquette) httpx"
LICENSE = "CC BY-SA 4.0"
ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "backend" / "data" / "hue.sqlite"
PROPOSALS = Path(__file__).resolve().parent / "guide_proposals.json"
OUTPUT = ROOT / "backend" / "app" / "data" / "guide_corpus.json"

HERITAGE_CATEGORIES = ("historic", "religious", "attraction", "museum", "park")
OTHER_TOP_N = 30
SEARCH_LIMIT = 3
BATCH_SIZE = 20
SLEEP_SECONDS = 1.0
SECTION_LIMIT = 900
SECTIONS_MAX = 3
TOTAL_LIMIT = 3500
# Level-2 headings whose folded text (no diacritics, lower case) contains one of these are kept.
SECTION_WANTED = (
    "lich su", "kien truc", "dac diem", "canh quan", "mo ta", "vi tri", "gia tri", "ten goi", "cau truc",
    "khung canh", "le hoi", "hien trang", "trung tu", "dia ly", "khi hau", "sinh thai", "du lich",
)
# Headings that are never kept, even when they also contain a wanted word.
SECTION_SKIPPED = (
    "tham khao", "chu thich", "lien ket ngoai", "xem them", "hinh anh", "thu vien anh", "ghi chu",
)
_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1$")

_RATING = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*5")

# poi_id -> exact Vietnamese Wikipedia title, checked by hand against the proposals file.
# Rejected after reading the leads: Quốc Tử Giám (hatnote in the lead), Hồ Thủy Tiên (the article is an abandoned water park),
# and two disambiguation pages (Nhà thờ Dòng Chúa Cứu Thế, Chùa Linh Quang).
PLACE_ARTICLES: dict[str, str] = {
    "huetripo:003939": "Cầu Dã Viên",
    "huetripo:019472": "Trấn Bình đài",
    "huetripo:034370": "Tranh làng Sình",
    "huetripo:051114": "Sân Đại Triều Nghi (Hoàng thành Huế)",
    "huetripo:057832": "Đàn Âm Hồn",
    "huetripo:067276": "Phủ Nội Vụ (Hoàng thành Huế)",
    "huetripo:097517": "Kỳ đài (Huế)",
    "huetripo:105922": "Chùa Thánh Duyên",
    "huetripo:117501": "Sông Ngự Hà",
    "huetripo:125699": "Chín Hầm",
    "huetripo:162001": "Cửu Đỉnh (nhà Nguyễn)",
    "huetripo:162453": "Triệu Tổ miếu (Hoàng thành Huế)",
    "huetripo:175774": "Lăng Hiệp Hòa",
    "huetripo:187639": "Sông Đông Ba",
    "huetripo:197559": "Chùa Thiên Mụ",
    "huetripo:197701": "Phước Tích",
    "huetripo:200310": "Điện Thái Hòa (Hoàng thành Huế)",
    "huetripo:204318": "Điện Hòn Chén",
    "huetripo:221788": "Thế Tổ miếu (Hoàng thành Huế)",
    "huetripo:227208": "Lăng Trường Diễn",
    "huetripo:235246": "Lăng Kiên Thái Vương",
    "huetripo:236539": "Xiển Võ từ",
    "huetripo:241704": "Thái Bình lâu (Hoàng thành Huế)",
    "huetripo:248230": "Thiền viện Trúc Lâm Bạch Mã",
    "huetripo:267265": "Điện Cần Chánh (Hoàng thành Huế)",
    "huetripo:268730": "Cửu vị thần công",
    "huetripo:282608": "Phá Tam Giang",
    "huetripo:285771": "Cầu Phú Xuân",
    "huetripo:290712": "Rú Chá",
    "huetripo:299952": "Hổ Quyền",
    "huetripo:300955": "Lăng Thiệu Trị",
    "huetripo:311187": "Lăng Trường Thanh",
    "huetripo:375618": "Bình An đường",
    "huetripo:380302": "Hưng Tổ miếu (Hoàng thành Huế)",
    "huetripo:395933": "Đầm Lập An",
    "huetripo:401118": "Đàn Nam Giao (triều Nguyễn)",
    "huetripo:419863": "Lầu Tứ Phương Vô Sự",
    "huetripo:424131": "Lăng Minh Mạng",
    "huetripo:433822": "Vườn Thiệu Phương",
    "huetripo:447608": "Cồn Dã Viên",
    "huetripo:449632": "Duyệt Thị đường (Hoàng thành Huế)",
    "huetripo:466852": "Hồ Tịnh Tâm",
    "huetripo:472680": "Ngọ Môn (Hoàng thành Huế)",
    "huetripo:473604": "Vườn quốc gia Bạch Mã",
    "huetripo:477283": "Cồn Hến",
    "huetripo:478411": "Triệu Tổ miếu (Hoàng thành Huế)",
    "huetripo:483480": "Lăng Tự Đức",
    "huetripo:483532": "Lăng Trường Hưng",
    "huetripo:487864": "Lăng Hiếu Đông",
    "huetripo:511996": "Lăng Dục Đức",
    "huetripo:512284": "Sông Hương",
    "huetripo:531787": "Hoàng thành Huế",
    "huetripo:544139": "Điện Voi Ré",
    "huetripo:553779": "Điện Cần Chánh (Hoàng thành Huế)",
    "huetripo:572465": "Ga Huế",
    "huetripo:586695": "Đình Phú Xuân",
    "huetripo:604306": "Đông Khuyết đài",
    "huetripo:613849": "Quan Tượng Đài",
    "huetripo:627150": "Lăng Khải Định",
    "huetripo:644703": "Phu Văn lâu",
    "huetripo:655246": "Điện Phụng Tiên (Hoàng thành Huế)",
    "huetripo:657208": "Hải Vân quan",
    "huetripo:664215": "Cầu Trường Tiền",
    "huetripo:667743": "Hiển Lâm các",
    "huetripo:672780": "Nhà thờ chính tòa Phủ Cam",
    "huetripo:676368": "Cầu ngói Thanh Toàn",
    "huetripo:685303": "Lăng Vĩnh Thanh",
    "huetripo:689381": "Lăng Gia Long",
    "huetripo:702970": "Lăng Đồng Khánh",
    "huetripo:710305": "Chùa Diệu Đế",
    "huetripo:718015": "Thác Mơ (Phú Lộc)",
    "huetripo:718541": "Thế Tổ miếu (Hoàng thành Huế)",
    "huetripo:721191": "Ngự tiền văn phòng",
    "huetripo:722669": "Viện Cơ mật (Huế)",
    "huetripo:726134": "Cảng thị Thanh Hà – Bao Vinh",
    "huetripo:736460": "Chùa Từ Đàm",
    "huetripo:749012": "Cung Diên Thọ",
    "huetripo:793429": "Tử Cấm thành (Huế)",
    "huetripo:835596": "Điện Kiến Trung",
    "huetripo:844371": "Lăng Cơ Thánh",
    "huetripo:848751": "Núi Bân",
    "huetripo:851447": "Cầu Chợ Dinh",
    "huetripo:860594": "Kinh thành Huế",
    "huetripo:862938": "Chùa Quốc Ân",
    "huetripo:865952": "Chùa Từ Hiếu",
    "huetripo:879481": "Cung Trường Sanh",
    "huetripo:903836": "Lăng Vĩnh Cơ",
    "huetripo:919050": "Miếu Long Thuyền",
    "huetripo:919464": "Cửu Đỉnh (nhà Nguyễn)",
    "huetripo:931460": "Phước Tích",
    "huetripo:937271": "Tây Khuyết đài",
    "huetripo:946056": "Miếu Tiên Y",
    "huetripo:948386": "Cung Khôn Thái",
    "huetripo:967120": "Thái Tổ miếu (Hoàng thành Huế)",
    "huetripo:970786": "Hồ Xã Tắc",
    "huetripo:984414": "Hưng Tổ miếu (Hoàng thành Huế)",
    "huetripo:995454": "Điện Voi Ré",
    "huetripo:997900": "Đàn Xã Tắc (Huế)",
}


def load_pois() -> list[dict[str, object]]:
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT id, name, category, attributes_json FROM places ORDER BY id").fetchall()
    finally:
        connection.close()
    pois = []
    for poi_id, name, category, attributes_json in rows:
        try:
            attributes = json.loads(attributes_json or "{}")
        except json.JSONDecodeError:
            attributes = {}
        match = _RATING.search(str(attributes.get("Đánh giá") or ""))
        rating = float(match.group(1).replace(",", ".")) if match else 0.0
        pois.append({"id": poi_id, "name": name, "category": category, "rating": rating})
    return pois


def select_candidates(pois: list[dict[str, object]]) -> list[dict[str, object]]:
    heritage = [p for p in pois if p["category"] in HERITAGE_CATEGORIES]
    others = sorted(
        (p for p in pois if p["category"] not in HERITAGE_CATEGORIES),
        key=lambda p: (-float(p["rating"]), str(p["id"])),
    )[:OTHER_TOP_N]
    return heritage + others


def propose() -> None:
    candidates = select_candidates(load_pois())
    proposals: dict[str, object] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for index, poi in enumerate(candidates):
            if index:
                time.sleep(SLEEP_SECONDS)
            response = client.get(
                API,
                params={
                    "action": "query",
                    "format": "json",
                    "list": "search",
                    "srsearch": f"{poi['name']} Huế",
                    "srlimit": SEARCH_LIMIT,
                },
            )
            response.raise_for_status()
            hits = response.json().get("query", {}).get("search", [])
            proposals[str(poi["id"])] = {
                "name": poi["name"],
                "category": poi["category"],
                "candidates": [hit["title"] for hit in hits],
            }
    PROPOSALS.write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PROPOSALS} with {len(proposals)} POIs")


def lead_text(extract: str) -> str:
    return re.sub(r"\s+", " ", extract).strip()


def fold(text: str) -> str:
    """Lower case without diacritics, so that "Lịch sử" and "lich su" compare equal."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return re.sub(r"\s+", " ", "".join(c for c in decomposed if unicodedata.category(c) != "Mn")).casefold().strip()


def sentence_trim(text: str, limit: int = SECTION_LIMIT) -> str:
    """The longest run of whole sentences from the start that fits `limit`; empty when the first one does not."""
    kept: list[str] = []
    length = 0
    for sentence in split_sentences(text):
        added = len(sentence) if not kept else length + 1 + len(sentence)
        if added > limit:
            break
        kept.append(sentence)
        length = added
    return " ".join(kept)


def split_sections(extract: str, lead_length: int = 0) -> list[dict[str, str]]:
    """Level-2 sections of a plain extract that have a wanted heading, in article order.

    Level-3 and deeper headings are folded into their level-2 parent, so a section's text is everything up to the
    next level-2 heading. The text before the first heading is the lead and is not returned. At most
    `SECTIONS_MAX` sections are kept, each trimmed to `SECTION_LIMIT` at a sentence end, and the lead plus the
    sections stay within `TOTAL_LIMIT` characters.
    """
    parts: list[tuple[str, list[str]]] = []
    for line in extract.split("\n"):
        match = _HEADING.match(line.strip())
        if match:
            if len(match.group(1)) <= 2:
                parts.append((match.group(2).strip(), []))
            continue  # level-3+ headings are dropped; their text stays with the current level-2 parent
        if parts:
            parts[-1][1].append(line)

    sections: list[dict[str, str]] = []
    total = lead_length
    for heading, lines in parts:
        if len(sections) >= SECTIONS_MAX:
            break
        folded = fold(heading)
        if any(word in folded for word in SECTION_SKIPPED):
            continue
        if not any(word in folded for word in SECTION_WANTED):
            continue
        text = sentence_trim(re.sub(r"\s+", " ", " ".join(lines)).strip())
        if not text or total + len(text) > TOTAL_LIMIT:
            continue
        total += len(text)
        sections.append({"heading": heading, "text": text})
    return sections


def fetch_leads(titles: list[str]) -> dict[str, dict[str, object]]:
    """Return {requested title: article record} for the titles that have a non-empty lead."""
    fetched: dict[str, dict[str, object]] = {}
    retrieved_at = date.today().isoformat()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for start in range(0, len(titles), BATCH_SIZE):
            if start:
                time.sleep(SLEEP_SECONDS)
            batch = titles[start : start + BATCH_SIZE]
            response = client.get(
                API,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "titles": "|".join(batch),
                    "redirects": "1",
                    "prop": "extracts|info",
                    "exintro": "1",
                    "explaintext": "1",
                    "inprop": "url",
                },
            )
            response.raise_for_status()
            query = response.json()["query"]
            # Follow normalization and redirects so each requested title maps to its final article.
            final_of = {item["from"]: item["to"] for item in query.get("normalized", [])}
            redirect_of = {item["from"]: item["to"] for item in query.get("redirects", [])}
            pages = {page["title"]: page for page in query["pages"]}
            for requested in batch:
                title = final_of.get(requested, requested)
                title = redirect_of.get(title, title)
                page = pages.get(title)
                if page is None or page.get("missing"):
                    print(f"missing on Wikipedia: {requested}")
                    continue
                lead = lead_text(page.get("extract") or "")
                if not lead:
                    print(f"empty lead, dropped: {requested}")
                    continue
                url = page["fullurl"]
                fetched[requested] = {
                    "title": page["title"],
                    "url": url,
                    "license": LICENSE,
                    "authors_url": f"{url}?action=history",
                    "retrieved_at": retrieved_at,
                    "lead": lead,
                }
    return fetched


def fetch_extract(client: httpx.Client, title: str) -> str:
    """The full plain-text extract of one article, with level-2 and deeper headings as "== x ==" lines."""
    response = client.get(
        API,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "extracts",
            "explaintext": "1",
            "exsectionformat": "wiki",
        },
    )
    response.raise_for_status()
    pages = response.json()["query"]["pages"]
    return (pages[0].get("extract") or "") if pages else ""


def build() -> None:
    if not PLACE_ARTICLES:
        raise SystemExit("PLACE_ARTICLES is empty: curate the titles from guide_proposals.json first.")
    print("curated POIs:")
    for poi_id, title in PLACE_ARTICLES.items():
        print(f"  {poi_id} -> {title}")
    fetched = fetch_leads(sorted(set(PLACE_ARTICLES.values())))
    corpus = {poi_id: fetched[title] for poi_id, title in PLACE_ARTICLES.items() if title in fetched}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60) as client:
        for poi_id, record in corpus.items():
            time.sleep(SLEEP_SECONDS)
            extract = fetch_extract(client, str(record["title"]))
            record["sections"] = split_sections(extract, lead_length=len(str(record["lead"])))
            if not record["sections"]:
                print(f"no wanted sections: {poi_id} ({record['title']})")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(corpus)} of {len(PLACE_ARTICLES)} curated POIs")


def main(argv: list[str]) -> int:
    if "--propose" in argv:
        propose()
    else:
        build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
