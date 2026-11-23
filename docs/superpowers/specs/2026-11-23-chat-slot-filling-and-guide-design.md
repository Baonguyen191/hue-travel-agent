# Chat slot filling, trip summary, itinerary shape and tour guide: design

Date: 2026-11-23. Source: a role-play session where the assistant played the chatbot and the
user corrected each reply. Items marked **(assumed)** were proposed and not contradicted; the
user can still change them.

## Problem

The chat starts planning as soon as it has dates, length, origin and party size, so the user
gets a plan built on guesses. The plan then misreads the user's interests: "thiên nhiên, ngắm
cảnh" maps to the `park` category, which in the Hue data is mostly bridges, and `market`
includes malls and supermarkets. A real run for "Hà Nội → Huế, 24–26/11, 2 người, 6 triệu,
ẩm thực, thiên nhiên, ngắm cảnh" produced bridges, Vincom Plaza and Siêu thị GO!, with no café,
no sunset and no trip home. Place questions such as "Hồ Thủy Tiên có gì hay" get only metadata,
because 1,218 of 1,587 POIs have no description in the source.

## Target conversation

```
U: xin chào
B: (greeting template, unchanged)
U: tôi muốn đi Huế 3 ngày 2 đêm với người yêu
B: Bạn muốn đi Huế từ ngày nào?                      (2 people inferred, not asked)
U: ngày mai
B: Bạn xuất phát từ đâu?                              (no default)
U: Hà Nội
B: Mình ghi nhận: Hà Nội → Huế, 2 người, 24–26/11 (3 ngày 2 đêm).
   1. Ngân sách khoảng bao nhiêu cho cả chuyến?
   2. Hai bạn thích gì: di tích, ẩm thực, chùa chiền, thiên nhiên, cà phê ngắm cảnh…?
U: 6 triệu; ẩm thực, thiên nhiên, ngắm cảnh
B: <budget pre-check warning if the cheapest matching option exceeds the budget>
   Hai bạn muốn đi Huế bằng gì (xe giường nằm, tàu hỏa, máy bay), ở đâu (homestay, khách sạn, resort)?
U: giữ 6 triệu, xe giường nằm, homestay
B: 1. Lịch thong thả hay đi nhiều?  2. Có nơi nào nhất định muốn đến hoặc muốn tránh?
U: thong thả, không
B: <summary card, asks "Lên lịch nhé?">
U: thêm số lượng điểm đến, 3 điểm hơi ít
B: <summary again, pace line changed and marked "← đã đổi">
U: ok
B: <plan with clock times, travel legs, sunset slot, cost range; asks to approve or change>
U: hồ thủy tiên có gì hay
B: <guide answer from the stored Wikipedia article, with source; plan stays pending>
```

## Spec items

### S1. Ask until the trip is fully specified
No `orchestrator.start` until every required slot is filled and the user confirmed the
summary (S4).

| Slot | Rule |
|---|---|
| start date, length | required (today) |
| origin | required, **no default** (today: default Huế) |
| people | required; "với người yêu/vợ/chồng/bạn gái/bạn trai", "vợ chồng" means 2 (done) |
| budget_vnd | **required** (new) |
| interests | **required** (new): at least one category |
| transport_mode | asked once: `bus` \| `train` \| `flight`; "tùy" means cheapest |
| hotel_tier | asked once: `homestay` \| `hotel` \| `resort`; "tùy" means cheapest |
| pace | asked once: `relaxed` \| `moderate` \| `packed` (3 / 4 / 5 stops per day) |
| must include / avoid | asked once, optional; "không" ends it |

- At most **2 questions per turn (assumed)**, no choice buttons. The budget warning (S2) may
  share a turn with the transport/stay question.
- Each question turn starts with one line restating what was understood
  ("Mình ghi nhận: Hà Nội → Huế, 2 người, 24–26/11 (3 ngày 2 đêm).") **(assumed)**.
- Dates are restated as weekday plus date ("thứ Ba 24/11 – thứ Năm 26/11") **(assumed)**.
- Any answer may fill several slots; already-known slots are never asked again.

### S2. Early budget check
As soon as budget, transport mode and hotel tier are known (or budget plus interests if
those come first), estimate the cheapest matching total: transport both ways × people,
cheapest room of the tier × nights × rooms, food estimate, ticket medians **for the chosen
interest categories only** (S7). If the minimum exceeds the budget, say so with the
numbers and ask whether to raise the budget or keep it ("giữ 6 triệu" keeps it and plans
the cheapest option). Never plan silently over budget.

### S3. Interest mapping
- "ẩm thực" covers restaurants, cafés **and markets**.
- Markets used for food are only source type "Chợ" and "Cửa hàng đặc sản và quà tặng"; source
  type "Trung tâm thương mại" and names containing "siêu thị", "Vincom", "GO!", "mart" are
  never picked for food.
- "thiên nhiên", "ngắm cảnh", "hoàng hôn" map to attractions whose source type
  (`Loại hình (theo nguồn)`) is "Điểm du lịch, tài nguyên / Thiên nhiên" (56 POIs: Đồi Thiên An,
  Hồ Thủy Tiên, Đồi Vọng Cảnh, Sông Hương, Phá Tam Giang, Biển Thuận An…), not to the `park`
  category (bridges, public squares).
- Cafés with a view (name contains "garden", "riverside", "sông", "hồ", "view", "vườn") are
  preferred for "ngắm cảnh".

### S4. Summary and confirmation before planning
When S1 is complete, send a summary and wait:

```
Mình tóm tắt lại chuyến đi:
- Hành trình: Hà Nội → Huế, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm)
- Đoàn: 2 người, 1 phòng
- Ngân sách: 6 triệu (<pre-check note>)
- Đi lại: xe giường nằm · Chỗ ở: homestay
- Nhịp độ: vừa phải, 4 điểm tham quan mỗi ngày, có giờ nghỉ và hoàng hôn
- Ưu tiên: ẩm thực (quán ăn, cà phê, chợ), thiên nhiên, ngắm cảnh
Mình lên lịch theo thông tin này nhé? Nếu cần sửa gì, bạn cứ nhắn.
```

Pending kind `confirm_trip`. A confirm word starts the plan; any other message is read as an
edit to the draft (S5). Text only, no buttons (decided, Q3).

### S5. Edits at the summary
Apply the edit to the draft, resend the summary and mark changed lines with "← đã đổi".
"Thêm số lượng điểm đến" raises the pace one step.

### S6. "Điểm đến" counts sightseeing stops only
`visits_per_day` counts VISIT events. Meals and the café do not count.
relaxed = 3, moderate = 4, packed = 5 (decided, Q2). Each full day has lunch, dinner and one café
stop.

### S7. Pre-check uses the same categories as the plan
The pre-check and the real budget must price the same interest categories and tiers; the
role-play showed the pre-check at 6.35–7.76 M (with heritage tickets) against a real plan of
5.15–6.16 M.

### S8. Clock times with slot labels
Each event shows a clock time and its slot: Sáng, Trưa, Nghỉ trưa, Chiều (cà phê), Hoàng hôn,
Tối. A rest block after lunch is kept (decided, Q1). The sunset slot is an
estimate for the date (about 17:10 in late November in Huế) and is labelled as an estimate.
The sunset stop is a "Thiên nhiên" attraction or a bridge/riverside point.

### S9. Travel legs in the itinerary
For long overland trips the plan shows the outbound leg the evening before day 1 and the
return leg on the evening of the last day, with times from the chosen transport offer and the
MOCK label. Day 1 starts after arrival (drop luggage, check-in later); the last day ends with
check-out and a light meal before departure.

### S10. Tour guide (place descriptions)
- **Source: Vietnamese Wikipedia only (choice A).** A one-off script
  (`backend/scripts/build_guide_corpus.py`, same pattern as `build_photo_fallbacks.py`) fetches
  the articles for about 100–150 notable POIs with the etiquette User-Agent and stores
  `backend/app/data/guide_corpus.json`:
  `{poi_id: {title, url, license: "CC BY-SA 4.0", authors_url, retrieved_at: "YYYY-MM-DD", sections: [{heading, text}]}}`.
  POI-to-article links are curated by hand in the script.
- The huetripo `Tóm tắt` attribute (369 POIs) is also used, credited to huetripo.
- **No article and no summary means no description.** The bot says only what the data has and
  says the source has no description (as in the Hồ Thủy Tiên answer). The LLM never adds
  general knowledge.
- Where it shows:
  1. "X có gì hay / giới thiệu X": 3–5 sentences generated from the stored text, with the
     source line `Nguồn: Wikipedia tiếng Việt, CC BY-SA 4.0`.
  2. Itinerary: one short line per stop, taken from the stored text, shown only when a source
     exists.
  3. Place detail page: a "Giới thiệu" section with the source and license.
- **Architecture (assumed):** a capability of the chat/RAG layer, not a sixth agent, to keep
  the five-agent design in `IMPLEMENTATION_PLAN (1).md`. The guide text is indexed into the
  existing RAG store so place questions retrieve it.
- A place question while a plan is pending answers the question and leaves the plan pending.

## Data model changes

`TripRequest` (`backend/app/schemas/request.py`) gains:

| Field | Type | Default |
|---|---|---|
| `transport_mode` | `"bus" \| "train" \| "flight" \| None` | `None` = cheapest |
| `hotel_tier` | `"homestay" \| "hotel" \| "resort" \| None` | `None` = cheapest |
| `pace` | `"relaxed" \| "moderate" \| "packed"` | `"moderate"` |

Search and Budget filter offers by mode and tier. The Itinerary Agent reads `pace` for
`visits_per_day`, adds the café and sunset slots, and emits `TRANSPORT_OUT` / `TRANSPORT_BACK`
events. The chat draft (`backend/app/chat/draft.py`) tracks the new slots, the summary state
and changed fields.

## Work order

Each step is its own commit with tests; a Playwright scenario covers the target conversation.

1. **S3 interest mapping**: nature by source type, food markets only (`preferences.py`,
   `poi_search.py`). Smallest change with the biggest effect on plan quality.
2. **S1 slot filling**: required origin, budget and interests; optional mode, tier, pace,
   must/avoid; at most 2 questions per turn; restated understanding (`chat/draft.py`,
   `chat/texts.py`, `chat/service.py`, understanding prompt and fields).
3. **TripRequest fields** plus Search/Budget filtering by mode and tier.
4. **S2 + S7 budget pre-check** with the same categories and tiers.
5. **S4 + S5 summary and confirmation** with marked changes.
6. **S6 + S8 + S9 itinerary shape**: pace, café, sunset, rest, travel legs, clock times with
   slot labels (backend events plus `ItineraryTab` and chat plan card).
7. **S10 guide**: corpus script and data, RAG indexing, place answers, itinerary lines, detail
   page section.
8. **Evaluation**: add the target conversation and slot-filling cases to a new dev file;
   rerun the chat scenario suite and report before/after.

## Tests

- Unit: slot rules (required/optional, "tùy", couple inference), question batching, pre-check
  arithmetic, interest mapping (no bridges for nature, no malls for food), pace counts, travel
  legs, guide refusal when no source.
- Chat service: the target conversation turn by turn, edit at summary, place question during a
  pending plan.
- E2E (`frontend/e2e/chat.spec.ts`): the target conversation in the browser.

## Decisions (answered by the user, 2026-11-23)

- Q1. **Keep the rest block after lunch** (S8).
- Q2. **Pace steps 3 / 4 / 5 stops per day** for relaxed / moderate / packed (S6).
- Q3. **Text only at the summary step**, no buttons (S4).
- Q4. **Yes, one "why" line per stop.** It is built by code from facts, never written freely by
  the LLM: the matched interest ("hợp sở thích ngắm cảnh"), the slot ("điểm ngắm hoàng hôn"),
  the must-include request ("bạn muốn đến"), or the rating ("4,5/5, 197 lượt"). A stop with no
  such fact gets no line.
- Q5. **No.** "Với người yêu" only sets the party size to 2; it does not change which places
  are picked or the pace.
