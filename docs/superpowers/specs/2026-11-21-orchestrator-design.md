# Orchestrator (part 7a) + Vietnamese parser + CLI `plan` — design

Date: 2026-11-21. Sub-project 5a. Part 7b (Alembic, Postgres in compose,
docs) follows separately. MVP: Huế only.

## Problems found

1. Graph is Search → Budget → Itinerary → save. Budget never sees the
   itinerary's POIs, so admission/meals are not priced in the stored plan.
2. No validate node, no retry, no stop reason (plan test O01).
3. No `interrupt()`; approval is a separate store write; no checkpointer, so a
   restart loses graph state (plan test R01).
4. `TripRequestParser` needs `OPENAI_API_KEY`; none is configured, so every
   Vietnamese sentence falls back to "fill the form".
5. `orchestrator.py` and `api/plans.py` use `;`-chained one-liners.

## Design

### 1. Rule-based Vietnamese parser (`app/services/vi_request_parser.py`)

`parse_vietnamese_request(text, today: date) -> ParsedTrip` (reuse `ParsedTrip`
from `request_parser.py`; add `fields: dict` with what was extracted and
`notes: list[str]`). Work on `normalize_vietnamese(text)` but keep the original
for names. Never guess; a missing value goes to `missing_fields`.

- destination: known forms of Huế (`hue`, `thanh pho hue`, `thua thien hue`) →
  `"Huế"`; another known city name (`da nang`, `ha noi`, `ho chi minh`, `sai gon`,
  `hoi an`, `nha trang`, `da lat`) after `di`/`den`/`toi`/`du lich` → that city
  (Search later returns `UNSUPPORTED_DESTINATION`).
- origin: `xuat phat (tu)? X` or `tu X` where X is a known city → display name
  (`Hà Nội`, `TP. Hồ Chí Minh`, `Đà Nẵng`, …).
- duration: `N ngay (M dem)?` → days N; nights M or N−1.
- dates: `dd/mm(/yyyy)?` (first = start; second = end if present). Year
  defaults to the next occurrence on/after `today`. End = start + nights when
  only start + duration are known. No date → `start_date`, `end_date` missing.
- people: `N nguoi` / `N khach`; `vo chong`/`hai vo chong` → 2. Missing → missing.
- rooms: `N phong` (optional; default handled by TripRequest).
- budget: `ngan sach N trieu|tr|k|nghin|ngan|dong|d` and forms like `6.000.000`,
  `6,5 trieu` → integer VND.
- preferences: text after `thich`/`muon` up to the end or `.`/`;`, split on
  `,`, ` va `, ` voi `; keep original-case substrings.
- Returns `request` only when origin, destination, dates and people are all known.

`TripRequestParser.parse(text)` (existing endpoint `/plans/parse`):
run the rule parser first; only if fields are missing **and** an API key is
configured, call OpenAI to fill the missing fields only (never override).
Source: `RULES`, `RULES+OPENAI`, or `FORM_FALLBACK`.

### 2. Graph (`app/agents/orchestrator.py`, rewrite readable)

State (TypedDict): `request, owner_id, thread_id, search, itinerary, budget,
retries, attempts: list[str], status, warnings, plan_id, version, approval`.

Nodes: `search → itinerary → budget → validate →(cond)→ itinerary | approval | failed`.
- `itinerary`: uses an `ItineraryConfig` derived from the retry level:
  0 = default; 1 = `max_visits_per_day − 1`; 2 = also `cafe_break=False`;
  3 = also `max_visits_per_day = 2`.
- `budget`: `BudgetAgent.build(request, search, visit_poi_ids=itinerary.poi_ids())`.
- `validate`: problems = itinerary validation warnings + "no budget option".
  Over budget is **not** a problem (warning only; shortfall reported).
  No problems → `approval`. Problems and `retries < 3` → `retries += 1`,
  record the attempt reason, back to `itinerary`. Else → `failed`.
- `failed`: status `FAILED_VALIDATION`, warnings carry the reasons; END.
- `approval`: save plan (store.save_plan with owner) once per run, then
  `interrupt({"plan_id", "version", "options": labels, "status": "AWAITING_APPROVAL"})`.
  Resume value:
  - `{"action": "approve", "option": label, "user_id"}` → owner check, version
    check, `approve_option(...)` (existing quote service) → status `APPROVED`,
    `approval` in state; END.
  - `{"action": "edit", "request": {...}, "user_id"}` → owner check, replace
    request, reset retries → back to `search` (new version on next approval).
  - anything else / wrong owner → raise (API maps to 403/422).
- Node trace: each node appends its name to `attempts` style trace
  (`trace: list[str]`) for the demo.

Checkpointer (`app/agents/checkpoint.py`):
`open_checkpointer(url)` → `AsyncSqliteSaver` for a file path (default
`backend/data/checkpoints.sqlite`, env `CHECKPOINT_URL`), `AsyncPostgresSaver`
for `postgresql://…`, `InMemorySaver` for `memory://` (tests). `thread_id`
= the plan thread id. Orchestrator API:
- `async start(thread_id, request, owner_id) -> dict` (runs to interrupt/END)
- `async resume(thread_id, value) -> dict`
- `async state(thread_id) -> dict | None` (from checkpoint)
Returned dict: `status, plan_id, version, options, warnings, trace, retries`.

### 3. API (`app/api/plans.py`, rewrite readable; `bookings.py` unchanged)

- `POST /api/v1/plans/parse` → `TripRequestParser` (rules first).
- `POST /api/v1/plans/{thread_id}` body `TripRequest`, header `X-User-Id` →
  `start`; if the thread is waiting for approval, treat as edit (`resume` with
  `action: edit`).
- `GET /api/v1/plans/{thread_id}` → stored latest plan + checkpoint status;
  owner check (403).
- `POST /api/v1/plans/{thread_id}/approve` body `ApprovalRequest` →
  `resume(action=approve)`; stale version → 409; unknown option → 422;
  other owner → 403. Response keeps `ApprovalResult` shape.
- Endpoints are `async def`; no `asyncio.run` inside handlers.
- Orchestrator/checkpointer created in a FastAPI lifespan and closed on shutdown.

### 4. CLI `python -m app.demo plan "<câu tiếng Việt>"`

Flags: `--start YYYY-MM-DD` (fills a missing date), `--people`, `--origin`,
`--approve BUDGET|BALANCED|COMFORT`, `--book`, `--fail hotel`, `--json`,
`--checkpoint PATH` (default a temp file per run).
Output (Vietnamese):
1. "Phân tích câu" — extracted fields, missing fields, source.
   If still missing after flags → print what is missing + exit code 2.
2. "Chạy graph" — trace (`search → itinerary → budget → validate → approval`),
   retries with reasons.
3. Compact itinerary (one line per event, reuse itinerary_view helpers),
   compact budget (labels, totals, status, shortfall).
4. Status `AWAITING_APPROVAL` (plan_id, version).
5. With `--approve`: "Khởi động lại orchestrator từ checkpoint…" — build a
   **new** Orchestrator instance on the same checkpoint file, `resume` →
   `APPROVED` (quote_hash).
6. With `--book`: `BookingAgent` with key `demo-plan-key` → item lines as in
   the `book` demo (MÔ PHỎNG / TỰ LIÊN HỆ, contact lines only for the first 5 POIs
   plus "… và N địa điểm khác").

### 5. Dependencies

`backend/requirements.txt` adds `langgraph-checkpoint-sqlite>=3,<4` and
`langgraph-checkpoint-postgres>=3,<4` (already installed in `.venv`).

## Tests

- Parser: DoD sentence → origin Hà Nội, destination Huế, 3 days/2 nights,
  2 people, 6,000,000, preferences [di tích, đặc sản], missing start/end;
  with `05/12` → dates 2026-12-05..07 (today=2026-11-21); `6tr`, `500k`,
  `6,5 triệu`; "vợ chồng" → 2; Đà Nẵng destination kept (not Huế);
  missing people → in missing_fields; never invents.
- Graph: DoD → status `AWAITING_APPROVAL`; trace order search, itinerary,
  budget, validate, approval; stored payload budget has `admission` lines for
  itinerary POIs (i.e. visit ids were passed).
- O01: force validation failure (monkeypatched validator always failing) →
  `FAILED_VALIDATION` after exactly 3 retries, reasons present, no infinite loop.
- R01: start with a file checkpointer, drop the Orchestrator, create a new one
  on the same file, `resume(approve)` → `APPROVED`.
- Edit while waiting → version 2, old approval impossible (O02 via API).
- Wrong owner on resume → error; API 403.
- API: create → approve (TestClient) → book works end to end with `memory://`
  checkpointer via env in `tests/conftest.py`.
- Demo: `plan "<DoD>" --start 2026-12-05 --approve BUDGET --book` exit 0,
  contains `AWAITING_APPROVAL`, `APPROVED`, `MÔ PHỎNG`, `từ checkpoint`;
  without `--start` → exit 2 and mentions `start_date`.
- Existing tests keep their intent (update `test_orchestrator.py` /
  `test_booking_service.py` to the new `start`/`resume` API if needed).

## Out of scope (7b)

Alembic migrations, Postgres service wiring/healthcheck, README/PHASE_10 docs,
frontend.
