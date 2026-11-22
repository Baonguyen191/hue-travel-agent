# System metrics — Huế travel chat

Run date: 2026-11-22. Code at commit `3d1aac8` (branch `feat/hue-multi-agent`).

How to reproduce, from `backend/`:

```
..\.venv\Scripts\python -m app.evaluation.run --suite all --split dev
..\.venv\Scripts\python -m app.evaluation.run --suite all --split test
```

Run the commands one after the other and close other heavy apps first. Two runs on this
machine (16 GB RAM, RTX 4060 8 GB) were killed for low memory while the 9b judge was loaded.

| File | Content |
|---|---|
| `rag_dev.json`, `rag_test.json` | RAG suite: config, summary, one record per question |
| `agents_dev.json`, `agents_test.json` | Chat scenario suite: config, summary, one record per scenario |
| `before_tuning/` | Dev results before the tuning round (commit `355c042`) |

## Setup

| Item | Value |
|---|---|
| Understanding (extractor) | `qwen3.5:4b` (Ollama, local) |
| RAG generator | `qwen3.5:4b` |
| Embeddings | `bge-m3`, 1587 POIs indexed |
| Retrieval | BM25 + dense cosine, RRF k=60, top-5; "gần" anchor radius 2 km |
| Judge | `qwen3.5:9b` (local), with hard fact checks that override it |
| Transport, hotel, booking | Mock providers |
| Gold sets | `data/eval/rag_eval_v1.jsonl` (60 questions, 40 dev / 20 test), `data/eval/scenarios_v1.jsonl` (40 scenarios, 25 dev / 15 test) |

Dev was used for the one tuning round. Test was run once, after tuning, and never used to change code.

## Results

| Group | Metric | Dev before tuning | Dev after tuning | Test |
|---|---|---|---|---|
| RAG | Context precision | 0.764 | 0.926 | **0.907** |
| RAG | Context recall (capped, `min(|gold|, 5)`) | 0.672 | 0.850 | **0.853** |
| RAG | Faithfulness | 0.853 | 0.905 | **0.987** |
| RAG | Answer correctness (claim F1) | 0.567 | 0.568 | **0.599** |
| RAG (extra) | Refusal precision / recall | 0.615 / 0.80 | 1.00 / 0.80 | 1.00 / 1.00 |
| RAG (extra) | Citation hit rate | 0.80 | 1.00 | 0.93 |
| Multi-agent | Task success rate | 0.88 | 0.88 | **0.667** |
| Multi-agent | Routing accuracy (handler per turn) | 1.00 | 1.00 | **0.864** |
| Multi-agent | Tool correctness (exact set / precision / recall) | 0.92 / 1.00 / 0.93 | 0.92 / 1.00 / 0.93 | **0.733 / 1.00 / 0.730** |
| Multi-agent (extra) | Trace accuracy | 0.857 | 0.857 | 0.615 |
| Planning | Budget compliance rate | 0.75 (n=4) | 0.75 (n=4) | **0.50 (n=2)** |
| Planning | Schedule feasibility rate | 1.00 (20 plans) | 1.00 (20 plans) | **1.00 (9 plans)** |
| Planning | Constraint satisfaction rate | 0.778 (n=18) | 0.778 (n=18) | **0.636 (n=11)** |
| Performance | Chat turn latency p50 / p95 | 2.35 s / 4.54 s | 2.35 s / 4.54 s | **2.37 s / 4.65 s** |
| Performance | RAG answer latency p50 / p95 (see caveat 3) | 22.6 s / 26.1 s | 22.5 s / 24.1 s | 23.3 s / 28.3 s |
| Performance | Tokens per chat turn (prompt + completion) | 2099 | 2099 | **2109** |
| Performance | Tokens per RAG answer | 3025 | 3082 | **3084** |

The agent numbers did not change between dev runs because the tuning round touched only the RAG
code. The judge used 37k tokens on dev and 22k on test. These tokens are not counted in the
per-answer numbers.

### RAG by question group

| Group | n dev / test | CP dev → test | CR dev → test | Faithfulness dev → test | Correctness dev → test |
|---|---|---|---|---|---|
| single_place | 10 / 5 | 0.95 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 | 0.92 → 0.80 |
| near_place | 10 / 5 | 0.92 → 0.91 | 0.94 → 0.80 | 0.96 → 0.94 | 0.19 → 0.33 |
| by_category | 10 / 5 | 0.91 → 0.81 | 0.61 → 0.76 | 0.78 → 1.00 | 0.33 → 0.16 |
| unanswerable | 10 / 5 | – | – | 0.78 → – | 0.80 → 1.00 |

The dev values in this table are the post-tuning ones.

## Tuning round (dev only)

The dev run before tuning showed that "near X" questions failed (recall 0.41, correctness 0.15,
5 wrong refusals). Three causes were found and fixed:

1. **Wrong anchor.** The LLM extractor sometimes returned the category phrase as the place. In
   "Có quán cà phê nào gần chợ Đông Ba Huế không?" it linked "quán cà phê" to a café called
   "Quán Cà phê Chiều". The retriever now links the text after the last "gần" first (`b662b89`).
2. **Lost category filter.** Removing the place phrase from the question also removed the category
   word ("Cà phê gần Ga Huế"). Also, "chỗ" folds to "cho" (market), and "ăn gì" / "ăn trưa" did not
   map to restaurants. Fixed in `b662b89`, `03e42f5` and `3d1aac8`.
3. **No distance in the context.** The generator refused correct hits because nothing said they
   were near. Each context line now ends with "(cách <anchor> X km)", and one prompt rule explains
   it (`b662b89`).

Result on dev near_place: recall 0.41 → 0.94, precision 0.43 → 0.92, faithfulness 0.53 → 0.96.
Wrong refusals went from 5 to 0. On test, near_place recall is 0.80.

## Failure examples (after tuning)

1. **Correct near answer scored 0 for correctness** (dev ne05, "Quán ăn gần Ga Huế"). The answer
   names three restaurants 0.3–0.5 km away, and all of them are in the gold set. The reference
   answer names only the three nearest POIs, so claim F1 is 0. See caveat 4.
2. **List question answered with one place** (dev by03, "Chùa nào ở Huế được đánh giá cao?").
   The answer names only "Chùa Diêm Phụng". Context recall is 0.2.
3. **Unsupported generalisation** (dev by04, "Những cây cầu nổi tiếng ở Huế?"). "Huế có hai cây
   cầu nổi tiếng" is not in the context. Faithfulness is 0.33 and context recall is 0.2.
4. **Citation leaks into the shown text** (dev by07). The answer ends with
   "[huetripo:575981, huetripo:264100]". `CITE_RE` strips only single-id brackets, so a bracket
   with several ids stays in the text the user sees. This is a display bug.
5. **Unanswerable question answered with the wrong kind of place** (dev un05, "Homestay nào ở
   Huế rẻ dưới 300 nghìn?"). The answer offers "Hana Coffee &amp; Homestay" at 25.000đ–45.000đ,
   which is a café's drink price. The fact checker passes it because the price matches the record.
   The `&amp;` HTML entity also comes from the source data.
6. **Unanswerable question answered from neighbouring facts** (dev un07, "Quán nào ở Huế có menu
   tiếng Hàn?"). The answer lists Korean restaurants. The question was about the menu language.
7. **"Ở Huế" origin not understood** (dev s14 and s20; test s16, s23 and s37). "Ở Huế, 2 người,
   chơi 2 ngày từ 6/12" sets `request.origin`, but `fields.origin` stays missing, so the chat asks a
   clarifying question instead of planning. This is the largest single cause of agent failures.
   "Từ Huế, …" works.
8. **Category exclusions ignored** (dev s25 "không đi chùa", test s28 "không uống cà phê"). The
   phrase goes to `exclude` as a low-score place mention, not to `exclude_categories`, so the plan
   still contains temples or cafés.
9. **Category removal in a modify turn fails** (dev s31, "Bỏ chùa ra khỏi lịch"). It becomes
   `remove_place` with the text "bỏ chùa". This links to no place, and the turn ends in `failed`.
10. **Other edits fail** (test s32 "Đổi thành 4 người"; test s29 "đã đi Đại Nội rồi nên bỏ qua").
    Both turns end in `failed`. The people-count change and the "already visited, skip" phrasing
    are not handled.

Examples 7–10 are understanding-layer defects. They were found by this evaluation and were left
unfixed, because Task 8 was allowed to tune only the RAG components.

## Caveats

1. **Local judge.** `qwen3.5:9b` labels the claims and support. Hard fact checks override it for
   times, prices, phones and addresses. The judge failed on 1 dev answer and 2 test answers; those
   are excluded from faithfulness and correctness (see `n_scored` in the JSON). The judge is not
   deterministic, so expect a few points of run-to-run noise, for example unanswerable faithfulness
   1.00 → 0.78 between dev runs with no code change for that group.
2. **Small samples.** Test has 20 RAG questions and 15 scenarios. Budget compliance on test has
   n=2. Treat differences under about 0.1 as noise.
3. **RAG latency includes model swaps.** The 4b generator and the 9b judge do not both fit in
   8 GB VRAM, so Ollama reloads models between items. A RAG answer measured inside the chat suite,
   with no judge loaded, took 8.1 s. Treat the 22–23 s in the RAG suite as an upper bound.
4. **Correctness and gold strictness.** For near_place and by_category, the reference answer lists
   three example names, but the gold set has every POI within 1 km or every match. An answer that
   names other correct POIs gets low claim F1. Context recall is the better signal for these groups.
5. **Mock providers.** Transport, hotel and booking prices come from mocks (bus 400k per person
   per leg, homestay 350k per night). Budget compliance measures the planner's arithmetic and its
   handling of infeasible budgets, not real prices.
6. **Default opening hours.** 377 POIs carry the default 07:30–17:30. Schedule feasibility checks
   against these hours, so a 1.00 rate does not prove that real hours fit. `unchecked_visits` is 0
   in every run.
7. **One embed failure per run.** One `/api/embed` call returned 500 during a model reload in each
   of dev run 1 and test. That question used BM25 only (`mode_counts`).
