# Itinerary Agent completion + CLI demo — design

Date: 2026-11-21. Sub-project 3 (Search → Budget → **Itinerary** → Booking →
Orchestrator). MVP scope: Huế only, real `poi_id`s only.

## Problems found (DoD request, 2026-12-05 → 07, prefs "di tích", "đặc sản")

1. All 13 scheduled VISITs are restaurants; zero historic sites. Selection
   sorts by Search score and restaurants score higher (~98 vs ~80).
2. Lunch is an anonymous `MEAL_BREAK`; no dinner.
3. Iconic sites rank low in Search because the source has few reviews for them
   (Đại Nội Huế: 17 reviews) — they never reach the itinerary.
4. No distance limit: 46/251 historic POIs are > 15 km from the centre
   (e.g. Hải Vân Quan).
5. Days are filled by count (4) and nearest-from-centre, not by area or time.
6. Data error: Cầu Trường Tiền `visit_minutes = 600`.
7. Validator reports `valid=True` for all of the above.

## Design

### 1. Roles

- Sightseeing categories: `historic, religious, attraction, museum, park, market`.
- Food categories: `restaurant, cafe` — only scheduled as meals/cafe breaks,
  never as VISITs.

### 2. Config (`ItineraryConfig`, validated)

- `day_start 08:00`, `sightseeing_end 17:30`
- `lunch_earliest 11:30`, `lunch_minutes 75`
- `dinner_earliest 18:00`, `dinner_minutes 75`
- `cafe_break: bool = True`, `cafe_earliest 15:00`, `cafe_latest 16:30`, `cafe_minutes 45`
- `buffer_minutes 15`, `travel_speed_kmh 20.0`, `max_visits_per_day 4`
- `min_visit_minutes 30`, `max_visit_minutes 180` (clamp source/default durations)
- `center_lat 16.4698`, `center_lon 107.5786` (Đại Nội; used when the request has no centre)
- `max_distance_km 15.0`, `meal_radius_km 2.0`
- `landmark_ids` (ordered tuple, real ids from hue.sqlite):
  `huetripo:531787` Đại Nội Huế, `huetripo:197559` Chùa Thiên Mụ,
  `huetripo:483480` Lăng vua Tự Đức, `huetripo:627150` Lăng vua Khải Định,
  `huetripo:424131` Lăng vua Minh Mạng, `huetripo:759007` Chợ Đông Ba Huế,
  `huetripo:664215` Cầu Trường Tiền.
- Keep `_DEFAULT_VISIT_MINUTES` for missing durations.

### 3. `ItineraryAgent(config=None, places=None)`

`places: HuePlacesRepository | None`. Without it, landmarks not present in the
Search candidates are skipped and meals come only from candidates. Public
`plan(request, search) -> ItineraryResult` keeps its signature.

**Sightseeing pool** (ordered by priority):
1. Landmarks (config order, resolved via candidates then `places.get_by_id`;
   missing ids skipped silently) — included when the request's categories +
   mapped preferences (`map_preferences`) contain `historic` or `religious`,
   or when the request has no categories, preferences and keyword.
2. Search candidates in sightseeing categories, in Search order.
- Dedupe by `poi_id` and by `normalize_vietnamese(name)`.
- Drop places farther than `max_distance_km` from the centre, unless the
  normalized request keyword is contained in the normalized place name.
  Dropped ids go to `ItineraryResult.excluded_poi_ids` with one warning
  "N places farther than 15 km from the centre were skipped."

**Day assignment (area clustering)**, for each day in order:
- seed = first remaining place in priority order;
- day set = seed + nearest remaining places to the seed, up to `max_visits_per_day`;
- route = nearest-neighbour order from the centre over the day set;
- schedule the day (below). Places that do not fit return to the front of the
  remaining list (keeping priority) for later days; after the last day they
  are reported in `unplanned_poi_ids`.

**Day schedule** (hotel assumed at the centre; one global warning says so):
- `current = day_start`, location = centre.
- Before each visit: if lunch not done and `arrival + duration > lunch_earliest`,
  insert lunch at `max(arrival_at_restaurant, lunch_earliest)`.
  If `cafe_break`, cafe not done, and `current >= cafe_earliest` and
  `current <= cafe_latest`, insert a cafe break.
- Visit: travel by Haversine / speed; respect `parse_simple_opening_window`
  (arrive no earlier than opening; skip if the visit ends after closing);
  skip if the visit ends after `sightseeing_end`. Duration =
  clamp(`visit_minutes` or category default, min, max); a warning when clamped.
  BUFFER event after each visit as today.
- After the route: lunch if still not done (at `max(current, lunch_earliest)`);
  dinner at `max(arrival, dinner_earliest)`.
- **Meal choice**: unused restaurant (cafe for the cafe break) across the whole
  trip, from Search candidates first, then `places.list_by_category` if a
  repository is given. Rank key: `(distance > meal_radius_km, not is_hue_specialty,
  -(rating_value or 0), distance, poi_id)`. Distance from the current location.
  No candidate at all → anonymous `MEAL_BREAK` (old behaviour) + day warning.
- Meal events: kind `MEAL`, `poi_id`, `name`, `category`, `lat/lon`,
  travel fields, warnings incl. "Opening hours require verification…".

### 4. Schemas (`app/schemas/itinerary.py`)

- `ItineraryEventKind` adds `"MEAL"`; validator: `MEAL` requires `poi_id`.
- `ItineraryEvent` adds `meal: Literal["LUNCH", "DINNER", "CAFE"] | None = None`.
- `ItineraryResult` adds `excluded_poi_ids: list[str] = []` and method
  `poi_ids() -> list[str]` (VISIT and MEAL ids, chronological, no duplicates).

### 5. Validator additions (`itinerary_validator.py`)

Keep existing checks; add:
- VISIT whose category is `restaurant` or `cafe` → warning.
- Day with VISITs but no lunch (`MEAL` with `meal="LUNCH"` or a `MEAL_BREAK`) → warning.
- Same POI used twice as a MEAL across the trip → covered by the duplicate check.

### 6. Wiring

`app/api/plans.py`: `ItineraryAgent(places=repo)` (reuse the same repository
instance as Search/Budget). Orchestrator order unchanged in this sub-project.

### 7. CLI `python -m app.demo itinerary`

- Same shared request flags and `--scenario` as `search`/`budget`; `--json`.
- Runs Search → Itinerary → Budget(`visit_poi_ids=result.poi_ids()`).
- Text output per day, BUFFER events hidden:
  `08:00–10:30  [Tham quan] Đại Nội Huế (historic)  0.1 km ~1'  vé 200,000 VND/người [DATA]  giờ mở 07:30-17:30 (chưa xác minh)  huetripo:531787`
  Meals: `[Ăn trưa]`, `[Ăn tối]`, `[Cà phê]` with the place's reference range
  `150,000 – 200,000 VND (tham khảo)` or `giá chưa rõ`. FREE_CLAIM → `miễn phí theo nguồn`.
- Then: unplanned, excluded count, warnings, validation result; then a compact
  budget block: each labelled option (Tiết kiệm/Cân bằng/Thoải mái) with total
  range and status, plus the admission subtotal for this itinerary.
- `--json` prints `ItineraryResult.model_dump_json(indent=2)`.

## Tests (`tests/test_itinerary_agent.py`, plus demo tests)

Keep intent of existing tests (real ids, no overlaps, duplicate detection,
opening-window parser, one lunch per day). Add, using the DoD request with a
repository-backed agent:
- no VISIT is a restaurant or cafe; every day has a LUNCH and a DINNER `MEAL` with a real `poi_id`.
- Đại Nội Huế (`huetripo:531787`) is scheduled.
- no VISIT is farther than 15 km from the centre; Hải Vân Quan (`huetripo:657208`) is in `excluded_poi_ids`.
- no restaurant/cafe is used twice across the trip.
- Cầu Trường Tiền's visit is ≤ 180 minutes and carries a clamp warning (if scheduled; force it via a request whose candidates include it, or test the clamp helper directly).
- validator flags a hand-built day where a restaurant is a VISIT, and a day without lunch.
- agent without repository still produces a valid plan (landmarks only from candidates).
- `poi_ids()` returns VISIT+MEAL ids in order without duplicates.
- `tests/test_demo_cli.py`: `itinerary --scenario dod` exits 0, output contains
  `Đại Nội Huế`, `[Ăn trưa]`, `[Ăn tối]`, `Tiết kiệm`; `--json` parses.
- `test_orchestrator.py` / `test_booking_service.py` keep passing.

## Out of scope

Real road routing; day-of-week opening hours; arrival/departure times of
intercity transport; pipeline reorder (Orchestrator sub-project).
