# Frontend (Phase 9) — design + implementation plan

Date: 2026-11-22. UI language: Vietnamese. MVP: Huế only, all bookings MOCK.
Approved stack: React 18 + Vite + TypeScript + Tailwind (v4, `@tailwindcss/vite`)
+ Leaflet (`react-leaflet` 4.x, OpenStreetMap tiles with attribution).

## Architecture

- SPA in `frontend/`, React Router 6 with browser paths.
- Dev: `npm run dev` (Vite, port 5173) proxies `/api` and `/health` to
  `http://localhost:8000`. Prod: `npm run build` → `frontend/dist`, served by
  FastAPI on the same origin (no CORS).
- Backend change: after all API routes, a catch-all `GET /{path:path}` that
  serves `frontend/dist/index.html` for non-`api/` paths when dist exists, and
  real files from dist when they exist (assets). `/api/*` 404s stay JSON.
  Replace the current `app.mount("/", StaticFiles(...))`. Test with a temp dist.
- Identity: `userId` = random uuid in `localStorage` (`hue.userId`), sent as
  `X-User-Id` on every request; header shows "Người dùng thử: <short id> —
  chưa phải đăng nhập". `threadId` = uuid created on plan creation.
- `src/api/types.ts`: TS types mirroring the Pydantic schemas actually returned
  (read `backend/app/schemas/*.py`, `parsed_trip.py`, and the dict shapes from
  `backend/app/agents/orchestrator.py` `start/resume/state` and
  `api/plans.py` `get_plan`). `src/api/client.ts`: `fetch` wrapper adding
  headers, JSON, and typed errors: `ApiError {status, detail}` with helpers
  `isStale` (409), `isForbidden` (403), `isNotFound` (404).
- Map: use `CircleMarker` (no image icons → no bundler icon issues), colour by
  kind; straight `Polyline` between consecutive events labelled
  "đường chim bay (ước lượng)". Leaflet CSS imported once.
- Formatting helpers `src/lib/format.ts`: VND (`1.250.000 ₫`), ranges
  (`a – b ₫ (tham khảo)`), time `HH:mm`, dates `dd/mm/yyyy`.
- Layout: top nav (Lập kế hoạch · Khám phá Huế), persistent footer disclaimer
  "Xe, khách sạn và đặt chỗ là MÔ PHỎNG. Dữ liệu địa điểm: huetripo.hue.gov.vn
  (giấy phép chưa rõ)". Responsive: map below content under `md`.

## Screens

1. `/` **Nhập yêu cầu** — textarea (placeholder = DoD sentence) → `POST
   /api/v1/plans/parse` → editable form prefilled from `request` or `fields`:
   origin, destination (default Huế), start/end date, people, rooms, budget
   (VND), preferences (chips, add/remove), categories (8 toggles). Missing
   fields (from `missing_fields`) highlighted red with a note; submit disabled
   until valid. Submit → `POST /api/v1/plans/{threadId}` with a loading panel
   listing graph steps (search → itinerary → budget → validate → approval;
   static list animated while waiting; real `trace` shown after) → navigate to
   `/plan/:threadId`. `FAILED_VALIDATION` → show reasons, stay on form.
2. `/explore` **Khám phá Huế** — 8 category chips, search box (debounced
   300 ms → `/api/v1/places/search?q=`; empty query → `/api/v1/places?category=`),
   pagination (limit 24, offset), cards: name, category label (VN), rating
   (value + count or "chưa có"), price: reference range "(tham khảo, đơn vị
   chưa rõ)" / "miễn phí theo nguồn" / "giá chưa rõ", hours "… (chưa xác minh)",
   source link. Map of current page. `/explore/:poiId` detail: all normalized
   fields, raw attributes table, source URL, coordinates, warnings.
3. `/plan/:threadId` **Lịch trình + bản đồ** — loads `GET /api/v1/plans/{id}`
   (payload: request, search, itinerary, budget; checkpoint status). Header:
   status badge, version, plan id short. Tabs: Lịch trình | Ngân sách & duyệt |
   Đặt chỗ. Itinerary tab: day tabs; timeline (VISIT, MEAL lunch/dinner/cafe;
   hide BUFFER) with time, name (link to `/explore/:poiId`), category, travel
   km/min "ước lượng", ticket/price info, hours "chưa xác minh"; map for the
   selected day; warnings panel always visible (itinerary + search + budget
   warnings, excluded/merged counts, validation result). "Sửa yêu cầu" → form
   (reuse screen 1 component in edit mode, prefilled from payload.request) →
   `POST /plans/{id}` again → reload → version increments.
4. **Ngân sách & duyệt** tab — options table: label (Tiết kiệm/Cân bằng/Thoải
   mái or "—"), outbound, return, hotel, total range, status (VN text + colour),
   unknown count; expandable cost items with source tag
   `MOCK` / `DATA` (HUE_POI_SOURCE) / `ƯỚC TÍNH` / `CHƯA RÕ` and notes;
   shortfall banner. Approve button only on labelled options, only when the
   plan is waiting (`AWAITING_APPROVAL`); sends `{version, option}`; on success
   show APPROVED + quote hash; on 409 show "Kế hoạch đã có phiên bản mới — tải lại".
5. `/plan/:threadId/booking` (tab) **Đặt chỗ** — button "Đặt MÔ PHỎNG" disabled
   unless status is APPROVED (tooltip explains). Idempotency key = uuid stored in
   `localStorage` per `threadId+quote_hash` so repeated clicks reuse it. Result:
   overall status badge; transport/hotel rows (status, `MOCK-…` reference with
   "MÔ PHỎNG" badge, price, message); "Tự liên hệ" list for POIs (name, phone,
   address, source link); explanation lines; "Kiểm tra lại trạng thái" button
   (same key) visible when any item is UNKNOWN or status PARTIALLY_BOOKED/UNKNOWN.
   Persist last BookingResult in `localStorage` per thread for reload.

## States

Loading skeletons; error banner with API `detail`; partial-data banner when
search status is PARTIAL; 403 page "Kế hoạch thuộc người dùng khác"; 404 page.

## Tests (Vitest + React Testing Library + jsdom)

- `format.ts` unit tests.
- `client.ts`: adds `X-User-Id`, parses errors into `ApiError` (mock `fetch`).
- Request form: missing fields highlighted; submit disabled until valid.
- Timeline renders VISIT/MEAL, hides BUFFER (fixture JSON captured from the real
  API: save one `GET /api/v1/plans/{id}` response into
  `frontend/src/test/fixtures/plan.json` by running the backend once).
- Budget table: source tags, approve button only on labelled options.
- Booking button disabled when not APPROVED; enabled when APPROVED.
- `npm run build` and `npx tsc --noEmit` clean.
- Backend: pytest for the SPA fallback (deep link returns index.html, `/api/x`
  unknown stays JSON 404, asset served).

## Implementation plan (each step = one commit)

1. Scaffold: `npm create vite@latest`-equivalent files written by hand or via
   npm (react-ts), Tailwind v4 plugin, Router, layout/nav/footer, `api/`
   types + client + userId, `lib/format.ts`, Vite proxy, tests setup; backend
   SPA fallback + pytest; remove the old hand-written `frontend/dist/index.html`
   from consideration (dist is gitignored; `.gitkeep` and `.openai/hosting.json`
   untouched).
2. Explore screen + detail.
3. Request screen (parse + form + create + loading).
4. Plan page: itinerary tab + map + warnings + edit.
5. Budget & approval tab.
6. Booking tab.
7. Docker multi-stage (node build stage → copy dist), README frontend section;
   coordinator runs browser E2E.

## Out of scope

Real auth, i18n beyond Vietnamese, images (licence unclear), offline caching.
