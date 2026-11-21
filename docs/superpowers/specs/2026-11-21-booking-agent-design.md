# Booking Agent completion + CLI demo — design

Date: 2026-11-21. Sub-project 4 (Search → Budget → Itinerary → **Booking** →
Orchestrator). Follows IMPLEMENTATION_PLAN §9 (state machine + guards). MVP:
all bookings are MOCK ("MÔ PHỎNG"); POIs from hue.sqlite are never booked.

## Problems found

1. `BookingService.book` books **every** transport and hotel offer in the
   Search result (9 with current mocks), not the approved option.
2. Approval stores no chosen option, no quote hash, no version check.
3. No revalidation of price/availability before submitting.
4. `UNKNOWN` is never reconciled; a retry just returns the stored result.
5. Idempotency intent is written after booking → concurrent duplicates possible.
6. No owner check (plan test A01).
7. Restaurants/sights in the itinerary are not reported as
   `BOOKING_NOT_SUPPORTED_BY_DATASET` with contact info.
8. No `BookingAgent`; `store.py`, `booking_service.py`, `booking_mock.py`,
   `schemas/booking.py`, `api/bookings.py` use `;`-chained one-liners.

## Design

### 1. Schemas (`app/schemas/booking.py`, rewrite readable)

- `BookingStatus`: `PENDING, BOOKED, FAILED, UNKNOWN, PARTIALLY_BOOKED,
  RECONFIRM_REQUIRED, NOT_SUPPORTED_BY_DATASET`.
- `BookingItem`: `offer_id: str | None`, `poi_id: str | None`,
  `kind: Literal["TRANSPORT", "HOTEL", "POI"]`, `status`,
  `source: Literal["MOCK", "HUE_POI_SOURCE"]`, `reference: str | None`
  (always `MOCK-…` for mock bookings), `price_vnd: int | None`,
  `contact_url: str | None`, `contact_address: str | None`,
  `contact_phone: str | None`, `message: str | None`.
- `BookingResult`: `intent_id`, `status`, `items`, `plan_version`,
  `approval_id`, `quote_hash`, `explanation: list[str]` (Vietnamese, deterministic),
  `source: Literal["MOCK"] = "MOCK"`.
- `BookingRequest`: `idempotency_key` (8–200 chars), unchanged.
- `ApprovalRequest`: `version: int`, `option: Literal["BUDGET", "BALANCED", "COMFORT"]`.
- `ApprovalResult`: `approval_id`, `plan_id`, `version`, `option`, `quote_hash`,
  `selected_offers: list[dict]`, `status: "APPROVED"`.

### 2. Store (`app/db/store.py`, rewrite readable, same class name)

- `Trip.owner_id: str` (default `"anonymous"`).
- `Approval` adds `option: str`, `quote_hash: str`, `selected_offers: Text` (JSON),
  `created_at`.
- `BookingIntent` adds `trip_id`, `status`, `created_at`, `updated_at`;
  `idempotency_key` stays UNIQUE.
- Methods (keep existing ones working where tests use them; adjust callers):
  - `save_plan(thread_id, payload, owner_id="anonymous") -> (plan_id, version)`;
    a later save by a different owner on the same thread raises `PermissionError`.
  - `latest(thread_id)` adds `owner_id`.
  - `approve(plan_id, option, quote_hash, selected_offers) -> approval_id`;
    deactivates older approvals of the same plan.
  - `active_approval(plan_id) -> dict | None`.
  - `claim_intent(key, trip_id, payload) -> tuple[dict, bool]`: inserts a
    `PENDING` intent; on `IntegrityError` returns the existing row and `False`.
  - `update_intent(key, payload)`.
- `create_all` stays (Alembic is the Orchestrator/infra sub-project).

### 3. Mock booking provider (`app/providers/booking_mock.py`, readable)

- `MockBookingProvider(modes: dict[str, Mode] | None = None,
  reconcile: dict[str, Literal["BOOKED", "FAILED", "UNKNOWN"]] | None = None)`,
  `Mode = Literal["success", "fail", "timeout"]`.
- `book(offer_id, kind, intent_id) -> BookingItem`: success → `BOOKED`,
  reference `MOCK-{intent_id[:8]}-{offer_id}`; fail → `FAILED`;
  timeout → `UNKNOWN` with message "Provider timed out; status will be reconciled."
  Records each call (for tests: no second create for the same offer+intent).
- `get_status(offer_id, intent_id) -> BookingItem`: from `reconcile`
  (default `UNKNOWN`); never creates a booking.

### 4. Revalidation

`QuoteRevalidator(transport_provider, hotel_provider)` re-runs the provider
searches with the plan's request and compares each approved offer by `id`:
missing → offer `FAILED` "Offer no longer available";
price differs → `RECONFIRM_REQUIRED` with old/new price in the message.
`MockTransportProvider` and `MockHotelProvider` gain an optional
`price_overrides: dict[str, int] | None` constructor argument (tests/demo only).

### 5. `BookingAgent` (`app/agents/booking.py`)

`BookingAgent(store, provider, revalidator, places=None)`;
`book(thread_id, idempotency_key, user_id="anonymous") -> BookingResult`.
`BookingService` stays as a thin alias/wrapper so imports keep working
(or is replaced; update callers).

Order of guards (state machine of plan §9.2):
1. Plan exists (`LookupError` → 404); owner matches (`PermissionError("owner")` → 403).
2. Active approval for the **latest** version (`ApprovalRequiredError` → 409).
3. `claim_intent`: if the key already exists → if its status is `UNKNOWN` or
   has `UNKNOWN` items, reconcile via `get_status` for those items only, update and
   return; otherwise return the stored result unchanged. Never re-create.
4. Revalidate approved offers; any `RECONFIRM_REQUIRED` → save result with status
   `RECONFIRM_REQUIRED`, book nothing. (A new approval creates a new quote hash;
   the user must use a new idempotency key.)
5. Saga: outbound → return → hotel, only the approved offers.
6. POIs from the itinerary payload (`VISIT`/`MEAL` events): one `POI` item each,
   `NOT_SUPPORTED_BY_DATASET`, source `HUE_POI_SOURCE`, contact url/address/phone
   from the place (`places.get_by_id`, phone from `raw_attributes` if a phone-like
   key exists; inspect the data), message "Đặt trực tiếp với cơ sở; hệ thống không đặt chỗ này."
7. Overall status from transport/hotel items only: all `BOOKED` → `BOOKED`;
   some `BOOKED` → `PARTIALLY_BOOKED`; any `UNKNOWN` and none booked → `UNKNOWN`;
   else `FAILED`. Never `BOOKED` while a required item is not `BOOKED`.
   No automatic cancellation; explanation says refunds follow provider policy.
8. Update trip status to the overall status; persist the result.

### 6. API

- `POST /api/v1/plans/{thread_id}` (create/edit) reads header `X-User-Id`
  (default `anonymous`) and stores it as owner.
- `GET /api/v1/plans/{thread_id}`: owner check (403).
- `POST /api/v1/plans/{thread_id}/approve` body `ApprovalRequest`: owner check;
  `version` must equal latest (409 otherwise); option must exist in
  `payload.budget.options[].label` (422 otherwise); computes `quote_hash` =
  sha256 of canonical JSON of the selected offers (id, price, unit, dates, leg)
  plus version; returns `ApprovalResult`.
- `POST /api/v1/plans/{thread_id}/book` body `BookingRequest`, header `X-User-Id`:
  404 / 403 / 409 mapping as above; 200 with `BookingResult` otherwise
  (including `RECONFIRM_REQUIRED`, `PARTIALLY_BOOKED`, `UNKNOWN`).
- README: state that `X-User-Id` is an MVP ownership check, not authentication.

### 7. CLI `python -m app.demo book`

Shared request flags + `--scenario`; plus `--option BUDGET|BALANCED|COMFORT`
(default `BUDGET`), `--fail transport|hotel`, `--timeout hotel`,
`--price-change`, `--other-user`, `--json`. Uses an in-memory store
(`sqlite://`) and runs: Search → Itinerary → Budget(visit ids) → save plan.
Steps printed in Vietnamese:
1. "Đặt khi chưa duyệt → bị chặn (409)".
2. "Duyệt phương án Tiết kiệm (version 1, quote_hash …)".
3. Book with key `demo-key-1`: one line per item — `[MOCK] Xe đi … BOOKED  mã MOCK-…  (MÔ PHỎNG)`;
   POIs: `[TỰ LIÊN HỆ] Đại Nội Huế — https://huetripo…`.
4. "Bấm lại cùng key → cùng intent <id>, không đặt trùng".
5. With `--timeout hotel`: second call reconciles (`get_status`) and prints the change.
6. With `--price-change`: shows `RECONFIRM_REQUIRED` with old/new price; nothing booked.
7. With `--other-user`: shows 403-equivalent message.
Final explanation lines from `BookingResult.explanation`.

## Tests

- K01 not approved → `ApprovalRequiredError`, provider never called, no intent row.
- K02 timeout → `UNKNOWN`; second call with same key calls `get_status` only
  (no second `book` call) and moves to `BOOKED` when reconcile says so.
- K03 same key twice → identical result; two threads racing the same key →
  exactly one set of provider `book` calls.
- K04 hotel fails → `PARTIALLY_BOOKED`, transport items `BOOKED`.
- K05 itinerary POIs → `NOT_SUPPORTED_BY_DATASET`, contact_url set, never booked.
- Only approved offers booked: with 6 transport + 3 hotel mocks, exactly 3 provider calls.
- Price change → `RECONFIRM_REQUIRED`, zero `book` calls.
- O02 edit plan (new version) after approval → booking blocked (409);
  approving a stale version → 409 via API.
- A01 other user → 403 on GET, approve, book (API tests with `TestClient`).
- Approve unknown option → 422.
- quote_hash stable for same offers, different when a price changes.
- Demo: `book --scenario dod` exit 0, contains `MÔ PHỎNG`, `TỰ LIÊN HỆ`,
  `không đặt trùng`; `--fail hotel` contains `PARTIALLY_BOOKED`.
- Existing tests keep their intent; update `test_booking_service.py` to the new
  approve signature.

## Out of scope

Real authentication; Alembic/Postgres checkpoints; LangGraph interrupt;
pipeline reorder (Orchestrator sub-project); cancellation/refund flows.
