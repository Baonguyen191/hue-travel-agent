# Huế "Cung đình" UI with place photos — design

Date: 2026-11-23. Branch: `feat/hue-multi-agent`. Status: approved in brainstorming (vibe A, layout 1,
photo proxy with cache, sections 1–4).

## 1. Goal

Restyle the whole React frontend (`frontend/`) in one Huế imperial ("Cung đình") design system and
show a place photo wherever a place appears, above all in the itinerary. Text, logic and user flows
stay as they are. Two small additions: a welcome screen on the empty chat and an "Hỏi trợ lý về nơi
này" button on the place detail page.

Out of scope: new features in the planner, the understanding layer or RAG; a split chat/itinerary
layout; user accounts; dark mode.

## 2. Decisions

| Topic | Decision |
|---|---|
| Scope | All pages: chat, form, explore, place detail, plan (itinerary, budget, booking tabs), 404 |
| Vibe | A — Cung đình: son red, kim gold, giấy dó paper, Noto Serif headings, hồi văn ornament |
| Layout | One-column chat (as today); the plan stays a separate page with three tabs |
| Photos | Backend proxy that downloads each source photo once, resizes it, caches it on disk |
| Missing photo | Line-art SVG illustration per place category, never a broken-image icon |

## 3. Backend

### 3.1 Photo endpoint

`GET /api/v1/places/{poi_id}/photo?w={160|480|960}` in `backend/app/api/places.py`, logic in a new
`backend/app/services/photos.py`.

- Look up the place in the Huế repository. Unknown `poi_id` or a place without `photo_url`: 404.
- `w` must be one of 160, 480, 960; anything else, or a missing `w`: 422.
- The source URL comes only from the place's `photo_url`. Its host must be exactly
  `huetripo.hue.gov.vn` with scheme `https`; otherwise 404 and a warning log line. No other URL is
  ever fetched (no SSRF).
- Cache file: `backend/data/photo_cache/{poi_id with ":" replaced by "_"}_{w}.webp`. If it exists,
  return it.
- Otherwise download with `httpx` (timeout 10 s, follow redirects only to the same host, at most
  15 MB read; a larger body is rejected). Open with Pillow, apply EXIF orientation, convert to RGB,
  resize so the width is `w` (keep the aspect ratio; never upscale a smaller source), encode WebP
  quality 80. Write to a temporary file in the same directory, then `os.replace` into place.
- Upstream error, timeout, oversize body or an image Pillow cannot decode: 502, nothing is cached,
  error logged.
- Response: `image/webp`, `Cache-Control: public, max-age=2592000, immutable`.
- The cache directory is created on first use and is git-ignored (`backend/data/photo_cache/`).
- The HTTP client is injectable (a `transport` argument or a dependency) so tests never touch the
  network.
- New dependency: `Pillow` in `backend/requirements.txt`.

### 3.2 `poi_id` in the chat plan card

`backend/app/chat/schemas.py` `PlanItem` gets `poi_id: str | None = None`, and
`backend/app/chat/cards.py` `_item` copies `event.poi_id`. The frontend type `ChatPlanItem` gets
`poi_id: string | null`. Existing fields are unchanged.

## 4. Design system

### 4.1 Tokens (`frontend/src/index.css`, Tailwind v4 `@theme`)

| Token | Value | Use |
|---|---|---|
| `son` | `#7A1F1F` | nav, primary buttons, bot bubbles, headings |
| `son-dark` | `#5E1616` | hover and pressed state of son |
| `kim` | `#B8913F` | borders, ornaments, secondary buttons, recommended option |
| `kim-soft` | `#EFE3C8` | chips, illustration background, meal rows |
| `giay` | `#F6EFE1` | page background |
| `nga` | `#FFFAF0` | card background, user bubbles |
| `vien` | `#EAD9B0` | hairline borders |
| `muc` | `#2B1A12` | body text |
| `muc-soft` | `#6D5A43` | secondary text |
| `reu` | `#3F5A3A` | success, booked state, map accents |

Contrast rules: body text is `muc` or `muc-soft` on `giay`/`nga`; text on `son` is `nga` or
`#FBECC8`; text on `kim` is `muc`. `kim` is never used as a text colour on light backgrounds.
Every text/background pair used must meet WCAG AA (4.5:1 normal text, 3:1 large text).

### 4.2 Typography

Google Fonts with the Vietnamese subset, loaded in `frontend/index.html` with `display=swap`:
Noto Serif 600/700 for headings, place names and the logo; Be Vietnam Pro 400/500/600/700 for
everything else. Fallbacks: `Georgia, serif` and `system-ui, sans-serif`.

### 4.3 Ornaments (pure CSS, no image files)

- `Ornament` band: repeating son/kim hồi văn stripe, 6–8 px high, under the nav and at the top of
  large cards.
- Ô hộc grid: faint kim grid used as a background on heroes and empty states.

### 4.4 Shared components (`frontend/src/components/ui/`)

`Button` (variants `primary` son, `secondary` kim, `outline` son border; sizes sm/md), `Chip`
(per-category colours), `Card`, `SectionHeading` (Noto Serif, son), `Ornament`, `MockBadge`
("MÔ PHỎNG"), `Notice` (variants `warning` kim bar, `error` son bar, `success` reu bar),
`PlacePhoto`, `PlaceIllustration`.

### 4.5 `PlacePhoto`

Props: `poiId: string | null`, `name: string`, `category: string | null`, `size: "sm" | "md" | "lg"`
(maps to `w` 160 / 480 / 960), `className`, `aspect` (default 4:3; hero 16:9).

- Renders `<img src={`${API_BASE}/places/${encodeURIComponent(poiId)}/photo?w=…`} alt={name}
  loading="lazy" decoding="async">` (`API_BASE` from `src/api/client.ts`; the Vite dev proxy and the
  same-origin production build both serve it) inside a box with a fixed aspect ratio, so the layout
  does not shift.
- While loading: `giay` skeleton. On `onError`, or when `poiId` is null: `PlaceIllustration` for the
  category, `aria-hidden`, with the name still available to screen readers.
- `PlaceIllustration`: line-art SVGs in son and kim for historic (cổng thành), religious (chùa /
  tháp), restaurant (tô bún), cafe (phin), market (nón lá / sạp), park (cầu / sông), museum, and a
  default (hoa sen).

### 4.6 Map

Leaflet markers become numbered son circles with a kim ring; the day route is a dashed kim line.

## 5. Pages

- **Layout**: son nav with the "Huế Travel" logo in Noto Serif and the two links (active link has a
  kim underline), ornament band below, `giay` page, footer with the huetripo source note and the
  MÔ PHỎNG notice. Content max width about 64rem; one column on phones.
- **Trò chuyện (chat)**: user bubbles `nga` with `vien` border, bot bubbles `son`. Quick replies are
  outline buttons. Composer is a rounded field with a son send button.
  - Empty state (no messages): hero photo of Huế (Đại Nội via `PlacePhoto` lg), a greeting and four
    sample questions; clicking one fills the composer.
  - Plan card: ornament band; per day a heading and a strip of `PlacePhoto` sm thumbnails with time
    and name under each (items without `poi_id` show the illustration); the three budget options
    (the recommended one in kim); "Xem chi tiết lịch trình" link.
  - Place card: `PlacePhoto` md (16:9), name, chip, hours note, price, address, phone, source link.
  - Booking card: MÔ PHỎNG badge, statuses in reu.
- **Kế hoạch (plan layout)**: hero with the first visited POI's photo (lg, 16:9, dark gradient),
  route, dates, people and version; tabs Lịch trình / Ngân sách / Đặt chỗ as pills (active son).
- **Lịch trình tab**: per day a Noto Serif heading; a vertical dashed kim timeline; each visit is a
  card with a `PlacePhoto` md, a number badge, time range, price and category chip; travel rows
  between visits (km, minutes); meals with a POI use its photo, meals without one use an icon row
  on `kim-soft`; warnings as `Notice warning`; the day map below.
- **Ngân sách tab**: three option columns (recommended highlighted in kim), sourced cost items,
  son "Duyệt" button, shortfall and approval notices restyled.
- **Đặt chỗ tab**: transport and hotel cards with the MÔ PHỎNG badge, reu booked state, the existing
  retry and contact behaviour.
- **Khám phá Huế**: search field and category chips; grid of place cards with `PlacePhoto` md; the
  map.
- **Chi tiết địa điểm**: `PlacePhoto` lg hero, info panel, source link, and a primary button
  "Hỏi trợ lý về nơi này" that opens the chat with the composer pre-filled
  `"{name} có gì hay? Giờ mở cửa và giá vé thế nào?"` (via router state; it is not sent automatically).
- **Lập kế hoạch (form)** and **404**: same components; the 404 page uses the cổng thành
  illustration.

All existing Vietnamese texts, labels, routes and API calls are kept.

## 6. Errors

| Case | Behaviour |
|---|---|
| Photo: unknown POI, no `photo_url`, disallowed host | 404; frontend shows the illustration |
| Photo: upstream error, timeout, oversize, undecodable | 502, not cached, logged; frontend shows the illustration; the next request retries |
| Photo: bad `w` | 422 |
| Frontend API errors | existing `ErrorBanner` / `Toast` logic, restyled as `Notice error` |

## 7. Testing

- Backend pytest (fake transport, temporary cache directory):
  - first request downloads, resizes to the asked width, returns `image/webp`; the second request
    serves the cache with no upstream call;
  - a source narrower than `w` is not upscaled;
  - bad `w` gives 422; unknown POI and a place without photo give 404;
  - a `photo_url` on another host gives 404 with no network call;
  - upstream 500, timeout, oversize body and garbage bytes give 502 and leave no cache file;
  - `plan_card` items carry `poi_id`.
- Frontend vitest + Testing Library:
  - `PlacePhoto` builds the URL for each size and swaps to the illustration on `error` and when
    `poiId` is null;
  - the chat plan card renders one photo per item with a `poi_id`;
  - the itinerary timeline renders photos for visits and an icon for a meal without a POI;
  - the empty chat shows sample questions and a click fills the composer;
  - "Hỏi trợ lý về nơi này" navigates to the chat with the pre-filled text.
- All existing frontend and backend tests keep passing. A test that depended on an old CSS class is
  rewritten to query by role or text.
- `npm run build` (includes `tsc --noEmit`), `npm test` and the full pytest suite pass.

## 8. Visual check

After each page batch: run the backend with the rules extractor (no Ollama needed) and `vite dev`,
and take Chrome screenshots at 1280 px and 390 px of: chat (empty and with a plan), the three plan
tabs, explore, place detail, form and 404. Check Vietnamese diacritics render in both fonts, text
contrast, no horizontal scroll at 390 px, and photos/illustrations in the right places.

## 9. Delivery order

1. Backend: photo endpoint, Pillow, `poi_id` in chat plan items.
2. Design system: tokens, fonts, ornaments, `ui/` components, `PlacePhoto` and illustrations.
3. Layout, chat page and chat cards (with the welcome screen).
4. Plan layout and the three tabs.
5. Explore, place detail (with the "Hỏi trợ lý" button), form, 404.
6. Visual check across pages and fixes.
