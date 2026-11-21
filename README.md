# Hue Travel Multi-Agent

A deterministic, Huế-only trip planner built from five cooperating agents: Search,
Budget, Itinerary, Booking and an Orchestrator (LangGraph). The Orchestrator
validates a plan, pauses for human approval, and the Booking Agent books only
the approved option, idempotently. All transport, hotel and booking providers
are mocks.

For the diagrams (orchestrator graph, sequence, data model, booking states) see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). For the defence demo script see
[docs/PHASE_10.md](docs/PHASE_10.md).

## Status

| Agent | Status | What it does |
| --- | --- | --- |
| Search | Done | Ranks Hue POIs from the local read-only source; asks mock transport and hotel providers for offers. |
| Budget | Done | Prices transport, hotel, admission and meals in integer VND; labels each line `QUOTED`, `ESTIMATED` or `UNKNOWN`. |
| Itinerary | Done | Schedules real `poi_id` values into days with straight-line routing, visit durations and meal breaks. |
| Booking | Done (mock) | Books only the approved option after revalidation; idempotent per key; reconciles timeouts; POIs are contact-only. |
| Orchestrator | Done | LangGraph graph: validate with up to 3 retries, durable approval interrupt, Vietnamese rules parser. |

Infrastructure: Alembic migrations run at startup, Docker Compose runs the API
with Postgres for state and checkpoints, and `GET /health` reports each component.

## Setup (local)

Requirements: Python 3.11+ and a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

### Data placement

- The POI source is `data/hue.sqlite` (repository root, supplied out of band).
  Copy it to `backend/data/hue.sqlite`, which the backend reads in read-only mode.
  Neither file is modified by the code.
- Runtime state is written under `backend/data/` and is git-ignored:
  `travel_state.sqlite` (plans, approvals, bookings) and `checkpoints.sqlite`
  (graph state). Both paths are absolute, so the app behaves the same from any
  working directory.
- Migrations create the state schema on startup. If you have a database file from
  before the Alembic migrations (created by the old `create_all`), move it aside
  first: the migration cannot adopt existing tables and fails with
  `table trips already exists`.

### Licence

The Hue dataset identifies its source as `huetripo.hue.gov.vn`. Its licence field
says the licence is unclear and asks consumers to cite the source. Verify data and
image reuse rights with the owner before publishing or using the data commercially.

## CLI demos

Run from `backend/`. Each demo uses the local Hue source and deterministic mock
providers, so every transport and hotel line is labelled `[MOCK]`.

```powershell
cd backend
python -m app.demo search --scenario dod
python -m app.demo budget --scenario dod
python -m app.demo itinerary --scenario dod
python -m app.demo book --scenario dod
python -m app.demo plan "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người" --start 2026-12-05
```

Shared request flags (all subcommands except `plan`): `--scenario dod`,
`--origin`, `--destination`, `--start YYYY-MM-DD`, `--end YYYY-MM-DD`,
`--people`, `--rooms`, `--budget VND`, `--pref TEXT` (repeatable),
`--category CATEGORY` (repeatable), `--keyword TEXT`.

| Command | Extra flags |
| --- | --- |
| `search` | `--per-category N`, `--json` |
| `budget` | `--visit POI_ID` (repeatable), `--json` |
| `itinerary` | `--json` |
| `book` | `--option BUDGET\|BALANCED\|COMFORT`, `--fail transport\|hotel`, `--timeout hotel`, `--price-change`, `--other-user`, `--json` |
| `plan` (Vietnamese sentence) | `--start`, `--origin`, `--people`, `--approve BUDGET\|BALANCED\|COMFORT`, `--book`, `--fail hotel`, `--checkpoint PATH`, `--json` |

`plan` exit codes: `0` done, `2` the sentence is still missing fields (for
example `start_date`) or the flags conflict, `1` the graph did not stop at
approval. `--book` needs `--approve`. The full script with expected output is in
[docs/PHASE_10.md](docs/PHASE_10.md).

Audit the Hue source (read-only):

```powershell
python scripts/audit_hue.py
```

## API flow

Start the API from the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

Then open `http://127.0.0.1:8000/health`. The plan and booking endpoints read the
`X-User-Id` header (default `anonymous`) as the plan owner. This is an MVP
ownership check, not authentication.

The examples use `curl.exe` and read the JSON body from files, which avoids shell
quoting problems with Vietnamese text. Save these as files in the current folder:

`trip.json`

```json
{"origin": "Hà Nội", "destination": "Huế", "start_date": "2026-12-05", "end_date": "2026-12-07", "people": 2, "rooms": 1, "budget_vnd": 6000000}
```

`approve.json`

```json
{"version": 1, "option": "BUDGET"}
```

`book.json`

```json
{"idempotency_key": "readme-demo-key-1"}
```

Create a plan (it waits for approval), read it, approve it, then book:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/plans/readme-demo -H "Content-Type: application/json" -H "X-User-Id: alice" --data-binary "@trip.json"
curl.exe http://127.0.0.1:8000/api/v1/plans/readme-demo -H "X-User-Id: alice"
curl.exe -X POST http://127.0.0.1:8000/api/v1/plans/readme-demo/approve -H "Content-Type: application/json" -H "X-User-Id: alice" --data-binary "@approve.json"
curl.exe -X POST http://127.0.0.1:8000/api/v1/plans/readme-demo/book -H "Content-Type: application/json" -H "X-User-Id: alice" --data-binary "@book.json"
```

Other endpoints:

- `POST /api/v1/plans/parse` with `{"text": "..."}` parses a Vietnamese request (rules first).
- A second `POST /book` with the same key returns the same intent without a new provider call.
- A different `X-User-Id` gets `403`; booking before approval gets `409`; a stale `version` gets `409`.
- Read-only POI endpoints: `GET /api/v1/places`, `/search`, `/nearby`, `/{poi_id}`.

## Docker

```powershell
# Skip the copy if .env already exists.
copy .env.example .env
docker compose up --build
```

The image is multi-stage: a `node:24-alpine` stage builds the React app, and the
Python image serves it from `/app/frontend/dist`. Open **http://localhost:8000**:
chat at `/`, the request form at `/form`, Khám phá Huế at `/explore`.

Ollama runs on the Docker host, not in the container. Compose sets
`OLLAMA_URL=http://host.docker.internal:11434` and maps `host.docker.internal` to
the host gateway, so the backend reaches the host's Ollama on port 11434. Without
Ollama the chat still works on the rules (see [Chat](#chat)).

Then check the stack:

```powershell
curl.exe http://localhost:8000/health
```

`/health` returns `200` with `"status":"ok"` when all components are up, and
`503` with `"status":"unavailable"` when any is down. Components:

- `hue_source`: the Hue SQLite file opens read-only.
- `state_db`: `SELECT 1` through the state database engine.
- `checkpoint`: the checkpointer is open (Postgres also answers `SELECT 1`).

Compose services and volumes:

- `backend`: the FastAPI app on port 8000. It runs Alembic migrations on start, and
  `DATABASE_URL` and `CHECKPOINT_URL` point at Postgres. It restarts unless stopped.
- `postgres`: `postgres:16-alpine`, data in the named volume `pgdata`, not published to the host.

Environment variables are documented in `.env.example`. Compose sets
`DATABASE_URL` and `CHECKPOINT_URL` itself, so the values in `.env` do not
override them. `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` default to
`travel`; change the password for anything beyond local development.

Stop the stack with `docker compose down`. `docker compose down -v` also deletes
the `pgdata` volume, which removes all plans, approvals and checkpoints.

## Frontend

The UI is a React 18, Vite and TypeScript app in `frontend/`. The Docker build
uses Node 24.

```powershell
cd frontend
npm ci
npm run dev        # http://localhost:5173; proxies /api to the backend on port 8000
npm run build      # typecheck, then build to frontend/dist (FastAPI serves it)
npx tsc --noEmit   # typecheck only
npx vitest run     # component and unit tests (jsdom)
```

Start the backend on port 8000 before `npm run dev`. The chat tests use API
responses recorded in `frontend/src/test/fixtures/chat/`, so they need neither the
backend nor Ollama.

## Chat

The home page (`/`) is a chat. Write the trip in Vietnamese, one message at a time:

- `Tôi đi Huế 3 ngày 2 đêm từ 05/12, xuất phát Hà Nội, 2 người, ngân sách 8 triệu, thích di tích và đặc sản`
  creates a plan and shows its summary card with the budget options (Tiết kiệm, Cân bằng, Thoải mái).
- `Đại Nội mở cửa mấy giờ?` answers from the data. Opening hours are marked "chưa xác minh".
- `Duyệt BUDGET`, or the Duyệt button on the card, asks for confirmation. `đồng ý` approves, `huỷ` cancels.
- `Đặt vé và khách sạn` asks to book the approved option. `đồng ý` books it. Every booking is MÔ PHỎNG (mock).

Enter sends; Shift+Enter starts a new line. The conversation id is kept in the
browser (`localStorage`, key `hue.chatId`), so a refresh reloads the history.
"Cuộc trò chuyện mới" starts a new one. "Nhập bằng form" opens the request form at `/form`.

Each bot reply is tagged with what understood the message:
`Hiểu bằng: LLM (qwen3.5:4b)` when Ollama read it, or
`Hiểu bằng: luật (Ollama không chạy)` when the Vietnamese rules did.

### Ollama

The LLM step is optional. To use it, install Ollama and pull the model:

```powershell
ollama pull qwen3.5:4b
ollama serve
```

`OLLAMA_URL` (default `http://localhost:11434`) and `QU_MODEL` (default
`qwen3.5:4b`) choose the server and model. `QU_ENABLED=false` turns the LLM off.
If Ollama is unreachable or its reply is invalid, the rules read the message and
the reply notes why. Prices, hours and bookings always come from the data, never
from the model.

## Tests

From the repository root:

```powershell
python -m pytest -q
```

The suite takes about two minutes. The test configuration (`tests/conftest.py`)
sets `DATABASE_URL=sqlite://` and `CHECKPOINT_URL=memory://`, so tests never
touch `backend/data`. The frontend tests run with `npx vitest run` in `frontend/`.

## Limitations

- Transport, hotel and booking providers are mocks. Nothing is booked for real.
- `X-User-Id` is not authentication; any caller can send any value.
- Distances are straight-line (Haversine), not road ETAs.
- Opening hours and prices from the source are not verified; they are labelled as such.
- The data licence is unclear; cite the source and check rights before any public use.
- Cancellation and refunds are not automated; they follow the provider's policy.
