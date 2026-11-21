# Search Agent completion + CLI demo — design

Date: 2026-11-21. Sub-project 1 of "finish each agent in pipeline order"
(Search → Budget → Itinerary → Booking → Orchestrator). Each agent gets a CLI
demo so results are visible without a frontend.

## Problems found on real data (hue.sqlite, 1,587 POIs)

| Input | Current result | Cause |
|---|---|---|
| `preferences=["di tích","đặc sản"]` (the MVP Definition-of-Done sentence) | 0 POIs | preferences are joined into one string and fuzzy-matched against names |
| `categories=["historic","restaurant"]` | 50 POIs, all restaurants | single global ranking, then cut to 50 |
| no filters | top = Pizza Hut, Izakaya | ranking is rating-only; no Hue-local signal |
| `keyword="quan ca phe"` | top = "Quán Càng Ghẹ" | category words in the keyword are not used |

## Design

### 1. `backend/app/services/preferences.py` (new, pure functions, no I/O)

- `PREFERENCE_CATEGORIES`: normalized phrase → categories. A preference string
  maps when, after `normalize_vietnamese`, it equals a phrase or contains it as
  a whole-word phrase.
  - historic, religious: `di tich`, `lich su`, `lang`, `lang tam`, `kinh thanh`, `co do`, `hoang cung`
  - religious: `chua`, `nha tho`, `tam linh`, `den thap`
  - restaurant: `dac san`, `am thuc`, `an uong`, `mon hue`, `quan an`, `nha hang`
  - cafe: `ca phe`, `cafe`, `coffee`
  - market: `cho`, `mua sam`
  - park, attraction: `thien nhien`, `cong vien`, `song nuoc`, `check in`, `song huong`, `phong canh`
  - museum: `bao tang`
- `KEYWORD_HINTS`: same idea for a free-text keyword, but without ambiguous
  short words (`cho`, `lang`, `chua` are excluded — they are also common
  non-place words). Includes `quan ca phe`, `ca phe`, `cafe`, `coffee`,
  `quan an`, `nha hang`, `dac san`, `di tich`, `bao tang`, `cho dong ba`,
  `cho dem`, `cong vien`.
- `map_preferences(prefs) -> tuple[list[PlaceCategory], list[str]]`: returns
  (categories in first-seen order, unmapped preference strings).
- `extract_keyword_hints(keyword) -> tuple[list[PlaceCategory], str | None]`:
  returns (hinted categories, residual query). The residual removes the hint
  phrase and filler tokens (`quan`, `tiem`, `o`, `tai`, `hue`); an empty
  residual becomes `None`.
- `HUE_SPECIALTY_TERMS`: `bun bo`, `com hen`, `bun hen`, `banh beo`,
  `banh khoai`, `banh nam`, `banh loc`, `che hue`, `nem lui`,
  `bun thit nuong`, `banh canh`, `mon hue`, `dac san`.
- `is_hue_specialty(place) -> bool`: restaurant whose normalized name or
  summary contains a specialty term.

### 2. Search Agent `_find_pois` (rewrite, same signature and output type)

1. Categories = request.categories ∪ mapped preferences ∪ keyword hints
   (first-seen order, no duplicates).
2. Query = keyword residual, else unmapped preferences joined, else `None`.
3. If categories are empty:
   - with a query: search all categories with the query (today's behavior);
   - without a query: default tourist mix `historic, restaurant, cafe, attraction, religious`.
4. For each category: `search_places(category=c, query=query, ...)`. If a
   query is set and the category was *not* hinted by the keyword (it came from
   categories/preferences) and returns 0 hits, re-run that category with
   `query=None` so explicitly asked categories are never empty.
5. Restaurant results get `+15` score (cap 100) when `is_hue_specialty`, then
   re-sorted by `(-score, id)` inside the category.
6. Interleave category lists round-robin (rank 1 of each category, then rank 2…)
   up to 50 total, skipping duplicate `poi_id`s. Order of `poi_candidates` is
   this interleaved order.
7. Empty-result warning, provider handling and statuses stay unchanged.

The `/api/v1/places/search` endpoint and `search_places` keep their current
behavior (existing tests depend on it).

### 3. CLI demo `backend/app/demo/__main__.py`

Run from `backend/`: `python -m app.demo search --scenario dod`.

- argparse with subcommand `search` (others added in later sub-projects).
- `--scenario dod` preset: origin `Hà Nội`, destination `Huế`,
  2026-12-05 → 2026-12-07, 2 people, 1 room, budget 6,000,000 VND,
  preferences `["di tích", "đặc sản"]`.
- Flags override the preset: `--origin --destination --start --end --people
  --rooms --budget --pref (repeatable) --category (repeatable) --keyword
  --per-category N (display only, default 5) --json`.
- Text output (UTF-8, no new dependencies): request summary; status and
  warnings; one table per category with rank, name, `poi_id`, score, rating
  (count), distance or `-`, source URL; transport and hotel offers, each line
  prefixed `[MOCK]` when `source == "MOCK"`, with price and unit.
- `--json` prints `SearchResult.model_dump_json(indent=2)`.
- Exposes `main(argv: list[str] | None = None) -> int` for tests.

## Tests (added to `tests/`)

- `test_preferences.py`: mapping of `di tích`, `đặc sản`, `cà phê`; unmapped
  passthrough; keyword hint `quan ca phe` → `cafe` with residual `None`;
  `bún bò` → no hint, residual `bun bo`; specialty detection.
- `test_search_agent.py` additions:
  - DoD preferences → both `historic` and `restaurant` present, first two
    candidates have different categories.
  - `categories=["historic","restaurant"]` → both present.
  - `keyword="quan ca phe"` → top 3 all `cafe`.
  - no filters → top restaurant is a Hue specialty.
- `test_demo_cli.py`: `main(["search","--scenario","dod"])` returns 0 and
  output contains `historic`, `restaurant`, `[MOCK]`; `--json` output parses.
- All 33 existing tests still pass.

## Out of scope

Budget/Itinerary/Booking/Orchestrator changes; LLM use; FTS5; frontend.
