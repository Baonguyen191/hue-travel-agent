# Budget Agent completion + CLI demo — design

Date: 2026-11-21. Sub-project 2 (Search → **Budget** → Itinerary → Booking →
Orchestrator). MVP scope: Huế only. Use `hue.sqlite` numbers wherever the data
has them; keep mock/estimate only where the data has nothing, always labelled.

## Problems found (DoD request: Hà Nội→Huế, 2026-12-05→07, 2 people, 6,000,000 VND)

1. Food counts nights (2), not days (3 days, 2 nights).
2. Admission is always one `UNKNOWN` line, although the data has reference
   prices (Đại Nội 200k, Minh Mạng/Tự Đức/Khải Định 150k…) and ~400 POIs with a
   source "free" claim.
3. Status is `UNKNOWN` whenever any unknown line exists, even when the known
   part is far below budget.
4. Only one option: mocks return one offer per leg and one hotel.
5. No in-city transport cost.

## Data facts used

- Restaurants: 342 with `REFERENCE_RANGE` (median min 150,000 / max 200,000).
  Cafes: 134 (median 25,000 / 60,000). Source gives **no unit**; we assume
  "per person per meal" and say so in the note.
- Sightseeing admission: `price_status` ∈ `REFERENCE_RANGE` (with
  `price_min_vnd`/`price_max_vnd`), `FREE_CLAIM`, `UNKNOWN`.
- No hotel, intercity transport or taxi data → mock/config estimate.

## Design

### 1. Schemas

- `app/schemas/offer.py`
  - `TransportOffer.mode: Literal["BUS", "TRAIN", "FLIGHT"] | None = None`
  - `HotelOffer.tier: Literal["HOMESTAY", "THREE_STAR", "FOUR_STAR"] | None = None`
- `app/schemas/budget.py`
  - `BudgetStatus` adds `"WITHIN_BUDGET_EXCLUDING_UNKNOWN"`.
  - `CostItem` adds `amount_max_vnd: int | None` (ge=0; validator: when both
    set, `amount_max_vnd >= amount_vnd`) and `poi_id: str | None = None`.
  - `BudgetOption` adds `known_total_max_vnd: int` (ge=0) and
    `label: Literal["BUDGET", "BALANCED", "COMFORT"] | None = None`.
  - `BudgetResult` adds `shortfall_vnd: int | None = None`.

### 2. Mock providers (all `source="MOCK"`, ids stable)

- Transport, each leg (`OUTBOUND` and `RETURN`), price per person per leg:
  - BUS `Hue Sleeper Bus Demo` 400,000 — keep ids
    `mock-transport-outbound-standard` / `mock-transport-return-standard`
  - TRAIN `Reunification Train Demo` 800,000 — ids `mock-transport-{outbound|return}-train`
  - FLIGHT `Hue Air Demo` 1,600,000 — ids `mock-transport-{outbound|return}-flight`
- Hotel, per room per night:
  - HOMESTAY `Old Quarter Homestay Demo` 350,000 — id `mock-hotel-homestay`
  - THREE_STAR `Riverside Hue Demo Hotel` 650,000 — keep id `mock-hotel-riverside-deluxe`
  - FOUR_STAR `Perfume River Demo Resort` 1,400,000 — id `mock-hotel-perfume-river`
- `empty`/`timeout` modes unchanged.

### 3. `BudgetConfig` (dataclass, validated)

- `include_food: bool = True`
- `food_per_person_per_day_vnd: int | None = None` — `None` = derive from data
  (below); an int = fixed override (old behavior, `ESTIMATED`, `BUDGET_CONFIG`).
- `restaurant_meals_per_day: int = 2`, `cafe_visits_per_day: int = 1`
- `local_transport_per_day_vnd: int | None = 300_000` (whole group; `None` → omit line)
- `guests_per_room: int = 2`, `max_options: int = 10`

### 4. `BudgetAgent(config=None, places=None)`

`build(request, search, visit_poi_ids: list[str] | None = None) -> BudgetResult`.
Orchestrator call `build(request, search)` keeps working. `days = nights + 1`.

**Data medians** (`price_min_vnd` median, `price_max_vnd` median as `int`) for
restaurant and cafe `REFERENCE_RANGE` places: from `places.list_all()` when a
repository is given (compute once, cache), else from `search.poi_candidates`.
No priced places → that food line is `UNKNOWN`.

**POI lookup** for `visit_poi_ids`: `search.poi_candidates` first, then
`places.get_by_id`. Not found → `ValueError(f"Unknown poi_id: {poi_id}")`.

**Cost lines** per option (P = people, D = days):
- `transport_outbound`, `transport_return`, `lodging`: as today (`QUOTED`, source of the offer).
- `local_transport`: per_day × D, quantity D, unit `VND_PER_GROUP_PER_DAY`,
  `ESTIMATED`, source `BUDGET_CONFIG`.
- Food (when `include_food`; otherwise one `UNKNOWN` `food_estimate` line):
  - fixed override → one `food_estimate` line (per person per day × P × D).
  - data mode:
    - each visited restaurant/cafe POI = one meal for the group: line code
      `meal`, `poi_id` set, amount = min × P, max = max × P,
      `ESTIMATED`, source `HUE_POI_SOURCE`, unit `VND_PER_PERSON_PER_MEAL_ASSUMED`;
      if that POI has no price, use the category median and say so in the note.
    - `food_restaurant_other`: remaining restaurant meals
      (`D × restaurant_meals_per_day − visited restaurants`, floor 0) × P × median range.
    - `food_cafe_other`: same for cafes.
    - lines with quantity 0 are not emitted.
- Admission:
  - no `visit_poi_ids` → one `admission_fees` `UNKNOWN` line (note: "No visits selected yet").
  - else one `admission` line per visited POI in historic/attraction/museum/religious/park/market:
    - `REFERENCE_RANGE` → min × P .. max × P, `ESTIMATED`, `HUE_POI_SOURCE`,
      note "Reference price from huetripo; assumed per person; verify before travel."
    - `FREE_CLAIM` → 0, `ESTIMATED`, note "Free according to source."
    - `UNKNOWN` → `UNKNOWN`.

**Totals and status**: `known_total_vnd` = Σ amount; `known_total_max_vnd` =
Σ (amount_max or amount). With budget B:
- B is None → `UNKNOWN`, remaining None.
- known min > B → `OVER_BUDGET`.
- known max ≤ B → `WITHIN_BUDGET` if no unknown line, else `WITHIN_BUDGET_EXCLUDING_UNKNOWN`.
- otherwise (range straddles B) → `UNKNOWN` + option warning "Estimated range straddles the budget."
- `budget_remaining_vnd = B − known_total_max_vnd`.

**Options, labels, cap**: enumerate all outbound × return × hotel (as today).
Sort by (status rank: WITHIN_BUDGET 0, WITHIN_..._EXCLUDING_UNKNOWN 1, UNKNOWN 2,
OVER_BUDGET 3; then `known_total_max_vnd`; then `unknown_item_count`).
Labels, one per option, assigned on the full list before capping:
- `BUDGET` = lowest `known_total_max_vnd` overall.
- `COMFORT` = highest `known_total_max_vnd` among within-budget options (both WITHIN statuses), if not already labelled.
- `BALANCED` = unlabelled within-budget option closest to the midpoint of the
  BUDGET and COMFORT totals (tie → cheaper), if any.
Keep labelled options plus the best others up to `max_options`, in sort order.

**Result warnings**: search warnings; missing-provider warnings (as today);
`people > rooms × guests_per_room` → "N people may not fit in R room(s)";
no within-budget option and B set → `shortfall_vnd = cheapest.known_total_vnd − B`
(only if > 0) and warning "Cheapest option exceeds the budget by X VND."

`app/api/plans.py` passes the repository: `BudgetAgent(places=HuePlacesRepository(...))`.

### 5. CLI `python -m app.demo budget`

- Shares all request flags and `--scenario` with `search` (refactor into a
  shared parent parser). New: `--visit POI_ID` (repeatable), `--json`.
- Default visits: first 6 sightseeing-category candidates of the Search result,
  printed as "Sample visits (Itinerary will choose the real list): …".
- Output: request summary; sample visits; options table (label shown as
  `Tiết kiệm` / `Cân bằng` / `Thoải mái`, outbound mode+price, return, hotel
  name+tier+price/night, total `min – max VND`, status, unknown count); detail
  of BALANCED (else COMFORT, else BUDGET, else first): one line per cost item
  with tag — `[UNKNOWN]` if price_kind UNKNOWN, else `[MOCK]` for MOCK source,
  `[DATA]` for `HUE_POI_SOURCE`, `[ESTIMATED]` otherwise — quantity, unit,
  amount or range, note; then totals, remaining, shortfall, warnings.
- `--json` prints `BudgetResult.model_dump_json(indent=2)`.

## Tests

`tests/test_budget_agent.py` (rewrite expectations; keep intent of old tests):
- bus + THREE_STAR option: transport 400,000×2×2, lodging 650,000×2, correct units.
- food uses 3 days for a 2-night trip.
- data medians equal `statistics.median` of repository prices (test computes them).
- admission for visits [Đại Nội Huế, one FREE_CLAIM POI, one UNKNOWN POI]
  (look up ids by name/status via the repository in the test): 200,000×2, 0, UNKNOWN.
- visited restaurant becomes a `meal` line and reduces `food_restaurant_other` quantity by one meal.
- unknown `poi_id` → `ValueError`.
- missing providers → transport/lodging `UNKNOWN`, never 0.
- repeatable: same input → identical `model_dump()`.
- `include_food=False` → food `UNKNOWN`.
- tiny budget (1,000,000) → all `OVER_BUDGET`, `shortfall_vnd > 0`.
- large budget (50,000,000) → status of options with unknown admissions is
  `WITHIN_BUDGET_EXCLUDING_UNKNOWN`; labels: BUDGET is min total, COMFORT is
  max within budget, each label used at most once.
- `max_options` cap ≤ 10 and labelled options kept.
- 5 people, 1 room → room warning.

Also: `tests/test_search_agent.py` offer counts become 6 transport / 3 hotels;
`tests/test_demo_cli.py` adds budget DoD run (exit 0, contains `[DATA]`,
`[MOCK]`, `Tiết kiệm`) and `--json` parse. All other existing tests pass unchanged.

## Out of scope

Pipeline reorder to Search → Itinerary → Budget (Orchestrator sub-project);
Booking fix; real provider APIs.
