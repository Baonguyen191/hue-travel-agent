# Query understanding: evaluation report (Part 1)

Eval set: `data/eval/query_eval_v2.jsonl` (150 sentences converted from v1; dev = q001-q100,
test = q101-q150). Reference date 2026-11-18. Harness: `backend/app/understanding/evaluate.py`.
Reproduce a row with, from `backend/`:

    python -m app.understanding.evaluate --extractor ollama --model qwen3.5:4b --split test --out ../reports/understanding/qwen3.5-4b_test.json

## Results

| Configuration | Split | Intent acc | Full match | Clarify P / R | Category F1 | Must / exclude exact | p50 latency |
|---|---|---|---|---|---|---|---|
| Rules (`vi_request_parser`) | dev | 1.00 | 0.41 | 0.40 / 1.00 | 0.84 | 0.94 / 1.00 | 0.1 ms |
| Rules | test | 0.74 | 0.28 | 0.00 / n/a | 0.54 | 0.82 / 0.94 | 0.1 ms |
| qwen3.5:4b (final prompt) | dev | 1.00 | 0.68 | 0.96 / 1.00 | 0.87 | 0.99 / 1.00 | 2.4 s |
| qwen3.5:4b (final prompt) | test | 0.96 | 0.68 | n/a / n/a | 0.65 | 0.96 / 0.98 | 2.4 s |
| qwen3.5:9b | dev | 1.00 | 0.71 | 1.00 / 1.00 | 0.88 | 0.99 / 1.00 | 3.9 s |
| qwen3.5:9b | test | 0.98 | 0.70 | n/a / n/a | 0.60 | 0.96 / 0.96 | 4.0 s |

Notes:
- "n/a" means the denominator is zero: the test split has no gold clarifications, and the 4b
  test run made no clarifications.
- qwen3.5:4b on dev **before** the one prompt/post-processing tuning round: intent 0.99, full
  match 0.55, clarify P/R 0.92/0.96, category F1 0.78 (`qwen3.5-4b_dev.json` was overwritten by
  the tuned run; the numbers are from the first run's console output).
- qwen3.5:9b: the first test run was stopped by the operating system for low memory and wrote
  nothing. The completed rerun is `qwen3.5-9b_test.json`: full match 0.70 against 0.68 for the
  4b, but about 1.7 times the latency (p50 4.0 s against 2.4 s). `qwen3.5-9b_dev.json` is the
  dev run of the same model: full match 0.71 against 0.68 for the 4b, category F1 0.88 against
  0.87, p50 3.9 s.
- Old v1 result (88% full match) used a different gold (interests and PlanRequest fields) and
  is not directly comparable with these numbers.

## Tuning history (dev only)

One round, on dev only. Test was run once, after the code was final.
1. Holiday phrases "Noel này", "Giáng sinh này" added to the date resolver.
2. Synonym layer for interest phrases the preference table misses: "ngắm cảnh", "tham quan",
   "văn hóa", "ăn vặt", "hải sản", "biển" and similar.
3. Prompt: soft requests (lãng mạn, yên tĩnh, người đi cùng) must go to soft_preferences, not
   interest_phrases; a vague trip request is plan_new; one more hand-written example.

Dev full match went 0.55 -> 0.68 and category F1 0.78 -> 0.87.

## Ten failure examples (qwen3.5:4b, test split)

| Id | Sentence | What went wrong |
|---|---|---|
| q109 | Đi Huế 3 ngày từ 19/12 với người yêu, ô tô, thích chỗ lãng mạn và hoàng hôn | Soft request ("lãng mạn") turned into interest categories historic, market, religious |
| q111 | Đi Huế 1 ngày 27/11 đi bộ, thích làng nghề truyền thống và đồ thủ công | Interest phrases mapped to historic and religious; gold has no category |
| q113 | Đi Huế 3 ngày từ 2/1, xe máy, thích kiến trúc cổ và nhạc cung đình | No category produced for "kiến trúc cổ" (gold historic) |
| q121 | ... phải đến lăng Minh Mạng và Kinh Thành | Both places linked correctly; categories gold historic, prediction empty |
| q124 | Lên lịch Huế 2 ngày từ 12/12, xe máy, đã đi Đại Nội rồi nên bỏ qua | Intent misread as modify_plan with a remove_place change; should be plan_new with an exclusion |
| q125 | Đi Huế 1 ngày 30/11, xe máy, phải có cầu ngói Thanh Toàn | Must-include place dropped entirely (no mention extracted) |
| q126 | ... không đi lăng tẩm, thích cà phê và chợ | exclude_categories gave historic and religious; the table maps "lăng" to religious too |
| q132 | ... muốn lên Bạch Mã, không đi chùa | Bạch Mã linked to a place, but gold has no must_include: possible gold omission |
| q133 | ... bắt buộc có lăng Khải Định, bỏ bảo tàng | "bảo tàng" put in exclude as a place (linked to Bảo tàng Hồ Chí Minh) instead of exclude_categories |
| q148 | Khách sạn nào gần Đại Nội? | Intent place_info (linked Đại Nội) where gold is out_of_scope (hotel question) |

## Error analysis

Test split, qwen3.5:4b, 16 full-match failures out of 50. Counts are per failed field:
`categories_ok` 11, `must_ok` 2, `exclude_categories_ok` 2, `intent_ok` 2, `exclude_ok` 1,
`changes_ok` 1.

1. **Category table over-maps history phrases (largest source).** `preferences.map_preferences`
   maps "lăng", "di tích", "lịch sử" to both historic and religious. The gold reads them as
   historic only. On dev this one cause accounts for 18 of 31 category mismatches. The table is
   shared with the planner, so it was left unchanged here. Recommended fix: split the table
   entry (heritage tombs -> historic; pagodas -> religious) in a planner-side change.
2. **Soft requests leak into interests.** Phrases such as "lãng mạn", "làng nghề", "người yêu"
   sometimes arrive in interest_phrases. The prompt was tightened on dev; test errors remain.
3. **Recall of must-include places.** One place mention is sometimes dropped (q125).
4. **Intent confusion.** A past-visit remark ("đã đi Đại Nội rồi") can be read as a plan change
   (q124), and a hotel question as place_info (q148).
5. **Gold questions.** q132 probably needs must_include Bạch Mã (the traveller wants to go
   there); the old gold left it out. Left as is; the gold was converted faithfully from v1.

Categories in gold follow one fixed reading of each old interest label (history -> historic,
culture -> museum, spiritual -> religious, food -> restaurant, coffee -> cafe, nature and
sightseeing -> park and attraction, shopping -> market, photography -> none). These are documented
in the converter, not in the eval file.
