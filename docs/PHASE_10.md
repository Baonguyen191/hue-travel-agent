# Phase 10: boundary and defence demo

This is the script for showing the MVP end to end. Every command below was run
against the current code; the key output lines are quoted from those runs.
Output is in Vietnamese; the key strings are kept as they appear.

Run everything from the repository root in PowerShell with the venv active,
unless a step says otherwise. The CLI commands use `python -m app.demo` from
`backend/`.

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
```

The sentence used throughout is the Huế sample trip:

```text
Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, ngân sách 6 triệu, thích di tích và đặc sản
```

The `--scenario dod` preset is the same trip in structured form (2026-12-05 to 2026-12-07, 2 people, 6,000,000 VND).

## 0. Safety notes (say these first)

- All transport, hotel and booking providers are **MOCK**. Every offer line
  says `[MOCK]` or `(MÔ PHỎNG)`; nothing is booked for real.
- Itinerary POIs are never booked by the system. They appear as `[TỰ LIÊN HỆ]`
  with the source's contact details, and the user contacts the place.
- `X-User-Id` is an MVP ownership check, not authentication. Do not expose the API publicly.
- The Hue source licence is unclear. Confirm data and image rights before public or commercial use.

## 1. Happy path: parse, plan, approve after a restart, book

```powershell
python -m app.demo plan "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, ngân sách 6 triệu, thích di tích và đặc sản" --start 2026-12-05 --approve BUDGET --book
```

Expected key lines (exit code 0):

```text
Phân tích câu (nguồn: RULES)
  Điểm đi: Hà Nội    Điểm đến: Huế
  Còn thiếu: không
Chạy graph
  search → itinerary → budget → validate → approval
Trạng thái: AWAITING_APPROVAL (plan <uuid>, version 1)
Khởi động lại orchestrator từ checkpoint checkpoints.sqlite…
Duyệt phương án Tiết kiệm (version 1, quote <hash>…)
Trạng thái: APPROVED
Đặt với khóa demo-plan-key → BOOKED
  [MOCK] Chuyến đi: ... BOOKED  mã MOCK-...  (MÔ PHỎNG)
  [TỰ LIÊN HỆ] Đại Nội Huế — https://huetripo.hue.gov.vn/...
```

What to point out:

- The graph trace shows the validation node before approval.
- `--approve` builds a **new** orchestrator on the same checkpoint file, so the approval crosses a restart.
- Without `--start`, the sentence has no dates and the command prints `Còn thiếu: start_date, end_date` and exits with code 2. This is the "ask, do not guess" rule.

Add `--json` for the raw final state and booking result.

## 2. Not approved: booking is refused (409)

Booking before approval is blocked. In the CLI the step is printed first:

```powershell
python -m app.demo book --scenario dod
```

Expected key line:

```text
1. Đặt khi chưa duyệt → bị chặn (409)
   Current plan version has not been approved.
```

The HTTP API does the same: `POST /api/v1/plans/{thread}/book` before approval returns **409**.

## 3. Double click: same key, one intent, no duplicate booking

The same command shows the idempotency guard:

```text
3. Đặt với khóa demo-key-1 → BOOKED
...
4. Bấm lại cùng khóa → cùng intent 5e682f90…, không đặt trùng (provider book calls: 3)
```

The provider was called 3 times (outbound, return, hotel) for the first press only. The second press returns the stored intent.

In the API, send the same `idempotency_key` twice; both responses have the same `intent_id`.

## 4. Hotel refuses: PARTIALLY_BOOKED

```powershell
python -m app.demo book --scenario dod --fail hotel
```

Expected key lines:

```text
3. Đặt với khóa demo-key-1 → PARTIALLY_BOOKED
  [MOCK] Chuyến đi: ... BOOKED
  [MOCK] Chuyến về: ... BOOKED
  [MOCK] Khách sạn: ... FAILED  mã -  (MÔ PHỎNG)
      ↳ Provider did not confirm the booking.
```

The plan demo has the same case: `python -m app.demo plan "<sentence>" --start 2026-12-05 --approve BUDGET --book --fail hotel` prints `→ PARTIALLY_BOOKED`.

The system does not cancel the transport tickets automatically; the explanation says cancellation and refunds follow the provider's policy.

## 5. Provider timeout: UNKNOWN, then reconcile

```powershell
python -m app.demo book --scenario dod --timeout hotel
```

Expected key lines:

```text
3. Đặt với khóa demo-key-1 → PARTIALLY_BOOKED
  [MOCK] Khách sạn: ... UNKNOWN  mã -  (MÔ PHỎNG)
      ↳ Provider timed out; status will be reconciled.
4. Bấm lại cùng khóa → đối soát (get_status), không đặt lại (provider book calls: 3)
   Khách sạn: Old Quarter Homestay Demo: UNKNOWN → BOOKED
   Trạng thái: PARTIALLY_BOOKED → BOOKED
```

The second press calls `get_status` only. It never sends the create request again while the state is unknown.

## 6. Price changed after approval: RECONFIRM_REQUIRED, nothing booked

```powershell
python -m app.demo book --scenario dod --price-change
```

Expected key lines:

```text
3. Đặt với khóa demo-key-1 → RECONFIRM_REQUIRED
  [MOCK] Chuyến đi: ... RECONFIRM_REQUIRED  mã -  (MÔ PHỎNG)
      ↳ Giá đã đổi từ 400,000 VND thành 500,000 VND; cần xác nhận lại.
  [MOCK] Chuyến về: ... PENDING  mã -  (MÔ PHỎNG)
4. Bấm lại cùng khóa → cùng intent 2fc02b95…, không đặt trùng (provider book calls: 0)
   Giá hoặc tình trạng đã đổi; chưa đặt gì. Hãy duyệt lại với khóa mới.
```

Zero provider `book` calls were made. The user must approve the new quote under a new idempotency key.

## 7. Another user: refused (403)

```powershell
python -m app.demo book --scenario dod --other-user
```

Expected key lines:

```text
Người khác cố đặt cùng plan → bị từ chối (403)
   owner: plan belongs to another user
```

The HTTP equivalent: a request with a different `X-User-Id` gets **403** on `GET`, `approve` and `book`.

## 8. Docker restart: a waiting plan resumes

Requires Docker. Start the stack, create a plan, restart the backend, then approve.

```powershell
docker compose up --build -d
curl.exe http://localhost:8000/health
# create a plan from trip.json (the JSON body is in README section "API flow")
curl.exe -X POST http://localhost:8000/api/v1/plans/demo-restart -H "Content-Type: application/json" -H "X-User-Id: alice" --data-binary "@trip.json"
docker compose restart backend
# approve.json holds: {"version": 1, "option": "BUDGET"}
curl.exe -X POST http://localhost:8000/api/v1/plans/demo-restart/approve -H "Content-Type: application/json" -H "X-User-Id: alice" --data-binary "@approve.json"
```

Expected:

- `/health` returns `200` with `"status":"ok"` and three components `ok: true`.
- After the restart the approve call returns `200` with `"status":"APPROVED"`.

The checkpoint lives in the `postgres` service (`pgdata` volume), so the paused graph survives the backend container restart. The same resume was also checked against a local `uvicorn` process that was stopped and started between create and approve.

## Limits to say out loud

- Providers are mocks; no real bus, hotel or payment integration.
- No real authentication; `X-User-Id` is a header anyone can send.
- Straight-line distances, not road ETAs; opening hours are unverified.
- Data licence is unclear; the source requires citation.
- Booking cancellation and refunds are not automated.
