# Hue Travel Multi-Agent

This repository includes PHASE 0–3: project setup, source auditing, normalized
read-only POI retrieval, local search/ranking, and explicitly-labelled mock
transport/hotel providers, a deterministic Search Agent, and a transparent
Budget Agent, and a deterministic Itinerary Agent. It does not yet provide
orchestration or booking.

## Dataset

`data/hue.sqlite` is the source file supplied for this project. PHASE 0 copies
it to `backend/data/hue.sqlite` for the backend to read. Both the audit script
and the API open the backend copy using SQLite read-only mode; neither command
changes the supplied source database.

If setting up from a clean checkout, put the source database at
`data/hue.sqlite`, then copy it to `backend/data/hue.sqlite` before starting the
API. Do not edit either file in place.

The dataset identifies its source as `huetripo.hue.gov.vn`. Its `license` field
states that the data licence is unclear and asks consumers to cite the source.
Verify data and image reuse rights with the owner before publishing or using
the data commercially.

## Run the audit

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python backend/scripts/audit_hue.py
```

The script uses `mode=ro` and reports integrity, record count, categories,
NULL rates, JSON keys, coordinate ranges, sources, and licences. Add `--json`
for machine-readable output or pass `--database <path>` to inspect another
SQLite copy.

## Run the API

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --reload
```

`GET /health` returns `200` when `backend/data/hue.sqlite` exists and can be
opened read-only. It returns `503` with a clear error when the file is absent
or unreadable. Set `HUE_SQLITE_PATH` only when intentionally pointing the API
at another read-only SQLite copy.

PHASE 1 also exposes these read-only endpoints:

```text
GET /api/v1/places?category=historic&limit=50&offset=0
GET /api/v1/places/huetripo:192068
GET /api/v1/places/search?q=dai%20noi&limit=10
GET /api/v1/places/nearby?lat=16.47&lon=107.58&radius_km=3
```

`category` accepts only the eight source categories. Search is local-only,
diacritic-insensitive, and returns a transparent score; nearby results use
straight-line (Haversine) distance, not road ETA.

## Phase 3 provider fixtures

`MockTransportProvider` returns outbound and return-leg bus fixtures, priced in
`VND_PER_PERSON_PER_LEG`. `MockHotelProvider` returns a Hue hotel fixture
priced in `VND_PER_ROOM_PER_NIGHT`. All such offers have `source: "MOCK"` and
cannot book anything. Each provider also supports explicit `empty` and
`timeout` modes for error handling tests. `HaversineRouteEstimator` produces
only straight-line distance and an `ESTIMATED` status; it never claims road ETA.

## Phase 4 Search Agent

`SearchAgent` combines source POIs with the provider interfaces concurrently.
It only supports Hue (`Huế`, `Thành phố Huế`, or `Thừa Thiên Huế`) and returns
`UNSUPPORTED_DESTINATION` elsewhere. Missing, empty, or timed-out providers
produce warnings and no inferred quote. `TripRequest` is structured input for
this layer; Vietnamese natural-language parsing arrives in Phase 7.

## Phase 5 Budget Agent

`BudgetAgent` enumerates compatible outbound/return transport and hotel offers,
then uses integer VND arithmetic. It labels each line `QUOTED`, `ESTIMATED`, or
`UNKNOWN`; only known lines are summed. Admission fees and unavailable provider
prices remain unknown and are never silently counted as zero.

## Phase 6 Itinerary Agent

`ItineraryAgent` schedules actual source `poi_id` values across calendar days,
using nearest-neighbour Haversine routing, visit-duration assumptions, a meal
break, and buffers. It labels all travel as estimated and all opening hours as
requiring verification; no road ETA or day-of-week opening claim is invented.

## Test

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```
