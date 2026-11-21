# 7b Infrastructure: config, Alembic, Docker, health, docs — design

Date: 2026-11-21. Follows the Orchestrator sub-project (7a).

## Problems found

1. `DATABASE_URL` default `sqlite:///backend/data/travel_state.sqlite` is
   relative to the CWD; running from `backend/` writes `backend/backend/data/`.
2. No Alembic; `create_all` cannot evolve an existing DB (the old
   `travel_state.sqlite` broke with "no such column").
3. Compose: no `CHECKPOINT_URL` (checkpoints live in the container file and are
   lost), no Postgres volume, hard-coded password, no backend healthcheck,
   no `.dockerignore` (build context uploads `.venv`).
4. `/health` checks only `hue.sqlite`.
5. README says "Phase 0–3"; `docs/PHASE_10.md` is 10 lines; no ERD/sequence diagrams.

## Design

### A. Config (`app/core/config.py`)

- `BACKEND_DIR` = absolute path of `backend/`; `DATA_DIR` = `BACKEND_DIR / "data"`.
- `database_url()` → env `DATABASE_URL` or `sqlite:///<abs DATA_DIR>/travel_state.sqlite`.
- `checkpoint_url()` → env `CHECKPOINT_URL` or `<abs DATA_DIR>/checkpoints.sqlite`.
  `app/agents/checkpoint.py` uses it (keep `memory://`, file path, `postgresql://`).
- `validate_settings()` → list of problems: URL scheme not in
  {`sqlite`, `postgresql+psycopg`} for DATABASE_URL; CHECKPOINT_URL not
  `memory://`, a path, or `postgresql://`; `OPENAI_API_KEY` optional (note only).
  Lifespan raises `RuntimeError` with all problems if any.
- `app/api/plans.py` uses `database_url()`.

### B. Alembic (`backend/alembic.ini`, `backend/migrations/`)

- `env.py` reads `database_url()`, `target_metadata = Base.metadata`
  (from `app.db.store`), `render_as_batch=True` for SQLite.
- Revision `0001_initial`: the four tables exactly as the current models
  (`trips`, `plan_versions`, `approvals`, `booking_intents`), incl. the UNIQUE
  `idempotency_key` and `thread_id`.
- `app/db/migrate.py`: `upgrade_to_head(url)` runs Alembic programmatically
  (`alembic.command.upgrade` with a `Config` built from `alembic.ini` path and
  `sqlalchemy.url` set).
- `PlanStore(url, create_schema: bool | None = None)`: `create_all` only when
  `url == "sqlite://"` (in-memory, tests) or `create_schema=True`; otherwise the
  schema must come from migrations.
- Lifespan: `upgrade_to_head(database_url())` before building the store/orchestrator.
- Test: migrating an empty temp SQLite file to head yields tables/columns equal
  to `Base.metadata` (compare with `alembic.autogenerate.compare_metadata` → no diffs).
- Test: `downgrade base` then `upgrade head` works.

### C. Docker

- `.dockerignore`: `.venv`, `.git`, `**/__pycache__`, `**/*.pyc`, `.pytest_cache`,
  `pytest-cache-files-*`, `backend/data/*.bak`, `backend/data/travel_state.sqlite`,
  `backend/data/checkpoints.sqlite*`, `frontend/node_modules`, `.env`, `docs`, `tests`.
  (Keep `backend/data/hue.sqlite` — the image needs it.)
- `docker-compose.yml`:
  - postgres: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-travel}` (same for user/db),
    named volume `pgdata:/var/lib/postgresql/data`, healthcheck as today.
  - backend: `DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-travel}:${POSTGRES_PASSWORD:-travel}@postgres:5432/${POSTGRES_DB:-travel}`,
    `CHECKPOINT_URL: postgresql://…same…`, `HUE_SQLITE_PATH`, `env_file: [.env]`
    marked `required: false`, healthcheck `python -c` urllib GET `/health`
    (no curl in slim image), `restart: unless-stopped`.
  - `volumes: { pgdata: {} }`.
- `backend/Dockerfile`: unchanged CMD (migrations run in lifespan); add
  `ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8`.
- `.env.example`: every variable with a one-line comment (`OPENAI_API_KEY`,
  `DATABASE_URL`, `CHECKPOINT_URL`, `HUE_SQLITE_PATH`, `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_DB`), no real secrets.

### D. `/health`

Response `{"status": "ok"|"unavailable", "components": {"hue_source": {...},
"state_db": {...}, "checkpoint": {...}}}`; each component `{"ok": bool,
"detail": str | None}`. `hue_source` = current read-only check; `state_db` =
`SELECT 1` through the store engine; `checkpoint` = the lifespan checkpointer is
open (and for Postgres a `SELECT 1`). Any component down → 503. Keep the
existing top-level `"database": "hue.sqlite"` and `"access": "read-only"`
keys for the hue part so the old health tests keep their intent (update the
tests to the new shape where needed).

### E. Docs

- `README.md` rewrite (Vietnamese headings fine, keep English technical terms):
  status of the 5 agents; local setup (venv, data placement, licence note);
  CLI demos (`search`, `budget`, `itinerary`, `book`, `plan` with flags);
  API flow with `curl` (create → GET → approve → book, `X-User-Id`);
  Docker (`docker compose up --build`, health, volumes, env); tests;
  limitations (mock providers, `X-User-Id` is not authentication, straight-line
  ETAs, unverified opening hours, data licence unclear).
- `docs/ARCHITECTURE.md`: mermaid diagrams — orchestrator graph (nodes,
  retry edge, interrupt), sequence create→approve→book (API, Orchestrator,
  agents, store, checkpointer, mock providers), ERD of the four tables, booking
  state machine (from IMPLEMENTATION_PLAN §9.2 as implemented). Short notes on
  data provenance and the five agents.
- `docs/PHASE_10.md`: defence demo script — commands and expected key output
  for: happy path (`plan … --approve BUDGET --book`), not approved (409),
  double click (same intent), `--fail hotel` (PARTIALLY_BOOKED),
  `--timeout hotel` (reconcile), `--price-change` (RECONFIRM_REQUIRED),
  `--other-user` (403), Docker restart resume; plus the safety notes already there.

## Tests

- config: defaults are absolute and independent of CWD (`monkeypatch.chdir`);
  invalid DATABASE_URL scheme → `validate_settings` problem; lifespan raises.
- migrations: compare_metadata empty; downgrade/upgrade round trip; PlanStore on a
  migrated file DB works (save_plan/latest).
- health: all ok → 200 with components; missing hue file → 503 with
  `hue_source.ok == false`.
- Full suite stays green (baseline 186).

## Verification (done by the coordinator, not the implementer)

`docker compose up --build -d`; `/health` 200; HTTP create → approve → book;
`docker compose restart backend`; a plan waiting for approval resumes.
