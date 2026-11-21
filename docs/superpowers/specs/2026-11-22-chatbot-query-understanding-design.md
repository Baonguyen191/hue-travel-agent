# Chatbot + Query Understanding — design

Date: 2026-11-22. Approved LLM: local Ollama `qwen3.5:4b` (already pulled;
`http://localhost:11434`). Three parts, each its own commits.

Context: the current `vi_request_parser.py` is regex rules only; the OpenAI
branch never runs (no key); the UI is one textarea → form. The old branch
`feat/stage0-1-foundation` had a hybrid rules+LLM understanding module
(`src/travel_agent/understanding/{models,normalize,dates,extract,link,ask,evaluate}.py`,
tests in `tests/understanding/`, eval set `data/eval/query_eval_v1.jsonl`,
150 sentences, reference date 2026-11-18) measuring qwen3.5:4b at 88% full
match, intent 1.0, field acc 1.0, interests F1 0.95, clarify P/R 1.0, p50 2.2 s.
Read them with `git show feat/stage0-1-foundation:<path>`.

Principle (kept from the old design): the LLM extracts; code decides.
The LLM returns date phrases verbatim ("cuối tuần này", "20/12"); code
resolves dates, maps interests, links place names to real `poi_id`s, fills
defaults, and decides clarification. The LLM never writes facts or numbers
shown to the user.

## Part 1 — Query understanding + evaluation

Package `backend/app/understanding/`:

- `models.py` — `Intent = plan_new | modify_plan | place_info | approve | book | out_of_scope`.
  `PlaceMention {text, poi_id | None, name | None, score}`.
  `PlanChange {kind: add_days | remove_days | set_dates | set_people | set_budget |
  cheaper | add_place | remove_place | exclude_category | include_category |
  set_hotel_tier | other, value: str | int | None, text}`.
  `ParsedQuery {intent, request: TripRequest | None, fields: dict,
  date_text, missing_fields, clarification: str | None, quick_replies: list[str],
  must_include: list[PlaceMention], exclude: list[PlaceMention],
  exclude_categories: list[PlaceCategory], soft_preferences: list[str],
  changes: list[PlanChange], place_query: PlaceMention | None,
  approve_option: BUDGET|BALANCED|COMFORT|None, source: OLLAMA|RULES, notes}`.
- `normalize.py` — port: diacritics folding (reuse `normalize_vietnamese`),
  abbreviations ("2n1đ", "3n2đ", "tr", "củ", "k"), number words ("hai", "ba").
- `dates.py` — port `resolve_date_text(text, ref)` (cuối tuần này, tuần sau,
  thứ 7 tới, mai, ngày kia, dd/mm, dd-mm-yyyy, đầu tháng 12, …) and
  `parse_duration` ("2 ngày 1 đêm", "2n1đ", "3 hôm", "một ngày").
- `link.py` — link place mentions to `HuePlacesRepository` by folded name
  (exact, then prefix/contains, then `difflib` ratio ≥ 0.8); ambiguous → keep
  top candidates in notes; never invent ids.
- `extract.py` — `OllamaExtractor(base_url, model, timeout=30)`: POST
  `/api/chat` with `format` = JSON schema of the raw LLM output (intent,
  verbatim date phrase, duration phrase, origin, people, rooms, budget phrase,
  interests phrases, must/exclude place phrases, exclude category phrases,
  soft preferences, change list, place question, approve option),
  `options.temperature=0`, `stream=false`, few-shot examples from the old
  prompt adapted to the new intents. Invalid JSON → retry once → raise
  `ExtractionError`. `think: false` if the model supports it (check the
  installed Ollama API; do not guess).
- `understand.py` — `understand(text, ref_date, context: ConversationContext | None)`:
  try Ollama; on connection error/timeout/`ExtractionError` fall back to the
  current rule parser (`vi_request_parser`) mapped into `ParsedQuery`
  (intent `plan_new` unless rules detect others), `source=RULES` and a note.
  Then code post-processing: dates, duration → end date, budget phrase → VND,
  interest phrases → categories via `preferences.map_preferences`, place
  linking, missing fields (`origin`, `start_date`, `people`; destination
  defaults to Huế; non-Huế city → `out_of_scope`), clarification text in
  Vietnamese + quick replies (e.g. "Cuối tuần này", "05/12", "2 người").
  With a context (an existing plan request), `modify_plan` changes are
  applied to a copy of that request by code (`apply_changes`).
- Config: `OLLAMA_URL` (default `http://localhost:11434`), `QU_MODEL`
  (default `qwen3.5:4b`), `QU_ENABLED` (default true).
- `TripRequestParser.parse` (`/plans/parse`) uses `understand()` so the form
  flow benefits too; response shape unchanged plus optional `parsed`.

Evaluation:
- `data/eval/query_eval_v2.jsonl` — convert the 150 old items (reference date
  2026-11-18) to the new gold shape: intent, start_date, end_date/num_days,
  origin/people/budget if stated, categories, must_include poi_ids,
  exclude, clarification expected (bool). Keep `id`, `group`, `split`
  (dev/test as in the old set; if absent, ids 1–100 dev, 101–150 test).
  Gold for fields the old set did not have (origin, people, budget) only where
  the sentence states them; otherwise omit (not scored).
- `backend/app/understanding/evaluate.py` + CLI `python -m app.understanding.evaluate
  --extractor rules|ollama --model qwen3.5:4b --split dev|test --out reports/understanding/<name>.json`.
  Metrics as the old harness: intent acc, per-field acc, categories exact/F1,
  must/exclude exact, clarification P/R, full match, errors, latency p50/p95,
  per-group.
- `reports/understanding/README.md` — table: rules vs qwen3.5:4b vs
  qwen3.5:9b on dev and test; 10 example failures of the best model.

Tests (no network): normalize, dates (port old tests), link (real DB),
extract with a fake HTTP transport (valid, invalid→retry, timeout), understand
fallback to rules, apply_changes, evaluate harness with fake predictions.

## Part 2 — Chat backend + constraints in agents

- `TripRequest` adds `must_include_poi_ids: list[str] = []`,
  `exclude_poi_ids: list[str] = []`, `exclude_categories: list[PlaceCategory] = []`.
  Search excludes them; Itinerary schedules must-include POIs first (as
  landmarks, never dropped for fillers; unknown id → validation error 422),
  never schedules excluded ids/categories (meals too for excluded categories).
- Alembic `0002_chat`: `conversations(id, owner_id, thread_id nullable,
  context_json, created_at, updated_at)`, `chat_messages(id, conversation_id FK,
  role user|assistant, text, payload_json, created_at)`.
- `app/chat/service.py` — `ChatService.handle(conversation_id, user_id, text)`:
  understand with context → dispatch by intent:
  - `plan_new`: missing → clarification reply (store draft in context);
    complete → orchestrator `start` (new thread) → reply with plan card.
  - `modify_plan`: needs a thread; `apply_changes` → orchestrator edit (resume
    `edit`) → reply with what changed + new version card.
  - `place_info`: data answer from the repository (hours raw + "chưa xác minh",
    reference price, address, phone, source link; "gần X" → nearby search 1 km
    top 5) — template text, no LLM wording.
  - `approve`: reply asking confirmation with the option and total; a second
    message "đồng ý"/"ok"/quick reply confirms → orchestrator approve.
  - `book`: only when approved; confirmation step as above → BookingAgent with
    a stored idempotency key per conversation+quote_hash.
  - `out_of_scope`: polite refusal (Huế only).
  Reply model: `ChatReply {message_id, text, cards: list[Card], quick_replies,
  pending_confirmation: dict | None, understanding: {intent, source, notes}}`;
  `Card` union: `plan_summary {thread_id, status, version, days: [{date, items: [time, name, kind]}],
  budget_options: [...]}`, `place {poi fields}`, `booking {result}`.
- API: `POST /api/v1/chat/{conversation_id}` (X-User-Id) `{message}` →
  `ChatReply`; `GET /api/v1/chat/{conversation_id}` → history. Owner checks (403).
- Tests: each intent path with a fake understand(); confirmation required
  before approve/book; owner check; must-include/exclude honoured by the
  Itinerary on real data (e.g. must include Lăng vua Gia Long, exclude chợ).

## Part 3 — Chat UI

- `/` becomes the chat page (keep a "Nhập bằng form" link to the existing form
  at `/form`). Message list, input with Enter-to-send, "đang suy nghĩ…" bubble,
  quick-reply chips, cards: plan summary (days, link "Xem chi tiết" →
  `/plan/:threadId`), budget options with "Duyệt" buttons that send the
  confirmation flow through chat, place card, booking card (MÔ PHỎNG badges,
  contacts). Small tag per bot reply: "Hiểu bằng: LLM (qwen3.5:4b)" or
  "Hiểu bằng: luật (Ollama không chạy)". Conversation id in localStorage;
  history reloads on refresh.
- Vitest for chat components with fixtures captured from the real API.
- Docker: `OLLAMA_URL=http://host.docker.internal:11434` + `extra_hosts:
  ["host.docker.internal:host-gateway"]` in compose.

## Out of scope

Training/fine-tuning; streaming tokens; voice; other cities.
