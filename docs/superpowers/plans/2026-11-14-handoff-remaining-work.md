# Bàn giao: hoàn thành SFT và RL cho planner Huế

- **Ngày:** 2026-11-14
- **Người đọc:** agent làm tiếp dự án, chưa có ngữ cảnh của các phiên trước.
- **Cách dùng:** đọc hết file này một lần. Sau đó làm từng chặng ở mục 6 theo đúng thứ tự. Mỗi chặng có "Điều kiện xong"; chưa đạt đủ thì chưa sang chặng sau.

## 1. Đích cuối

Dự án xong khi có đủ bốn thứ:

1. Bảng so sánh ba mốc trên **bộ test** (30 request): baseline `qwen3.5:4b`, SFT, SFT+RL. Cùng prompt, cùng candidate, cùng seed.
2. Model tốt nhất đã qua cổng thăng hạng, đã export GGUF, chạy được trong Ollama, có `model_card.json`.
3. `dvc repro` tái lập được toàn bộ pipeline từ dataset tới export. `scripts\check.ps1` xanh.
4. Báo cáo ghi đúng số đo được, kể cả khi SFT hoặc RL không cải thiện.

Mục tiêu của model là **tính hợp lệ** của lịch trình theo `validate_itinerary()`. Chất lượng "gu" nằm ngoài phạm vi (spec mục 1 và 3).

## 2. Tài liệu nguồn

| Tài liệu | Đọc khi nào |
|---|---|
| [Spec SFT và RL](../specs/2026-11-11-sft-rl-training-design.md) | Trước mọi chặng. Đây là căn cứ ràng buộc; khi file này và spec mâu thuẫn, hỏi người dùng. |
| [Việc còn mở trước SFT](2026-11-12-open-items-before-sft.md) | Chặng 1. Danh sách 10 mục và các mục nhỏ. |
| [Kết quả baseline](../../../reports/eval/README.md) | Chặng 1 và mỗi lần so sánh số đo. |
| [Plan 2](2026-11-11-plan-2-eval-baseline-mlops.md) | Khi cần mẫu về cách viết plan, hoặc cần biết vì sao harness eval có hình dạng hiện tại. |
| [README](../../../README.md) | Lệnh cài đặt, chạy pipeline, MLflow. |
| [Brief sản phẩm](../../../TRAVEL_AI_AGENT_CLAUDE_BRIEF.md) | Khi một quyết định chạm tới hành vi sản phẩm, ví dụ cấm bịa thông tin du lịch. |

## 3. Hiện trạng (2026-11-14)

- **Nhánh:** `feat/eval-baseline`, cây làm việc sạch, đi trước `main` 33 commit. Chuỗi nhánh: `main` → `feat/hue-data` → `feat/eval-baseline`. Chưa merge. Repo chưa có remote.
- **Đã xong:** validator, chọn candidate, prompt, parser, harness eval, cổng thăng hạng, DVC, MLflow, CI, chuẩn hóa giờ mở cửa huetripo. 199 test pass.
- **Chưa có:** `planning/solver.py`, `training/corrupt.py`, `training/reward.py`, thư mục `scripts/train/`, các file `configs/dataset.yaml`, `configs/sft.yaml`, `configs/grpo.yaml`, extra `train` trong `pyproject.toml`.
- **Baseline `qwen3.5:4b` trên 70 request dev:** `first_pass_valid_rate` 0,057 (4/70); `parse_error_rate` 0; `unknown_place_rate` 0,003.
  - Model luôn trả đúng 1 ngày: 0/49 request nhiều ngày đạt.
  - 57/70 request thiếu thời gian di chuyển. Một phần do candidate lấy từ toàn tỉnh, có cặp điểm cách nhau khoảng 4 giờ.
- **Ollama trên máy này** có sẵn 7 model cũ: `planner-sft-r1d-1000`, `-2000`, `-3000`, `planner-sft-r2`, `planner-grpo-g1-108`, `-216`, `-324`. Nguồn gốc chưa rõ: không biết train bằng prompt và dữ liệu nào. Không xóa, không ghi đè các model này.
- **Lệch giữa spec và code:** spec mục 2 ghi tối đa 20 candidate. Code dùng `clamp(max_stops × số ngày + 4, 12, 30)`. Chặng 1 phải chốt một con số và sửa bên còn lại.

## 4. Quy tắc bắt buộc

1. Nhắn cho người dùng bằng tiếng Việt.
2. Chỉ commit code, config, docs, file `.dvc` và `dvc.lock`. Để `data/hue.sqlite`, `data/raw/`, `*.gguf`, `.env`, adapter và checkpoint cho DVC hoặc `.gitignore` quản lý.
3. Hỏi người dùng trước khi push, merge, tạo remote, hoặc xóa bất cứ thứ gì ngoài cây làm việc.
4. Bộ test chỉ chạy **một lần**, ở chặng 5, bằng `--split test --allow-test`. Mọi quyết định trước đó dựa trên dev.
5. Bộ eval `data/eval/hue_eval_v1.jsonl` đã đóng băng. Giữ nguyên file và `frozen: true` của stage `make_evalset`.
6. Prompt có một nguồn duy nhất là `planning/prompt.py`. Baseline, dataset, train, eval và runtime đều gọi `build_messages()`. Đổi prompt thì cập nhật snapshot có chủ đích và chạy lại baseline.
7. Parser giữ nguyên output của model: output hỏng thì tính là hỏng. Dataset và reward cũng vậy.
8. Mọi nhãn SFT phải qua `validate_itinerary()` không có ERROR.
9. Siêu tham số nằm trong `configs/*.yaml`. Script đọc config, logic nghiệp vụ nằm trong `src/travel_agent/`.
10. Output training, cache DVC, DVC remote và MLflow nằm ngoài OneDrive: `C:\dev\travelagent-runs`, `C:\dev\travelagent-dvc-cache`, `C:\dev\travelagent-dvc`.
11. Khi gặp OOM hoặc lỗi công cụ, làm theo bảng ở spec mục 12. Đổi base model là quyết định của người dùng.
12. Ghi mọi số đo đúng như đo được. Một lần chạy không cải thiện vẫn là kết quả hợp lệ để báo cáo.

## 5. Môi trường: các bẫy đã gặp

- **Đường dẫn có dấu** (`OneDrive\Máy tính`): editable install hỏng. Luôn đặt `$env:PYTHONPATH="src"` rồi chạy `.venv\Scripts\python -m travel_agent <lệnh>`.
- **Console Windows dùng cp1252:** script in tiếng Việt cần `sys.stdout.reconfigure(encoding="utf-8")`. Chạy script rời bằng `python -I`.
- **`dvc freeze` không chạy được** với stage có tham số `${...}`. Đặt `frozen: true` bằng tay trong `dvc.yaml`.
- **Sau `dvc repro`:** commit `dvc.lock`, rồi `dvc push`.
- **Hook Fact-Forcing Gate:** lần đầu gọi Bash, Write hoặc Edit trong một phiên có thể bị chặn. Nêu các dữ kiện hook yêu cầu, rồi gọi lại đúng lệnh đó.
- **Kiểm tra trước mỗi commit:** `powershell -File scripts\check.ps1` (ruff, mypy, pytest). Phải xanh.
- **Ollama:** gọi `/api/chat` với `think: False`, schema viết tay `ITINERARY_FORMAT_SCHEMA`, `num_ctx` 8192. Giữ nguyên các thiết lập này cho mọi mốc để số đo so được.
- **Commit:** theo kiểu `feat:`, `fix:`, `chore:`, `docs:`, `test:`; message tiếng Anh; mỗi commit một việc.
- **Unsloth trên Windows native chưa kiểm chứng.** Nếu smoke test hỏng vì nền tảng, thử WSL2 và báo người dùng.

## 6. Các chặng

Quy trình chung cho chặng 1 tới 5:

1. Tạo nhánh mới từ nhánh người dùng chọn ở chặng 0.
2. Viết implementation plan vào `docs/superpowers/plans/`, theo mẫu Plan 2: từng task có file, interface, test viết trước, lệnh chạy, commit. Người dùng duyệt plan rồi mới code.
3. Làm theo TDD cho module logic thuần. Script GPU kiểm bằng smoke run.
4. Review toàn nhánh trước khi báo xong.
5. Cuối chặng, báo người dùng: số đo, các quyết định đã tự đưa ra, và rủi ro nếu quyết định đó sai.

Plan của chặng sau chỉ viết khi chặng trước xong, vì phụ thuộc interface và số đo thật.

### Chặng 0: chốt nhánh và đo model cũ

1. Hỏi người dùng: merge `feat/eval-baseline` về nhánh nào, và có tạo remote GitHub không. Chưa có remote thì CI chưa từng chạy.
2. Hỏi người dùng nguồn gốc 7 model `planner-*` trong Ollama.
3. Chạy eval dev cho từng model cũ, mỗi model khoảng 6 phút:

   ```powershell
   $env:PYTHONPATH="src"
   .venv\Scripts\python -m travel_agent eval --db data/hue.sqlite --evalset data/eval/hue_eval_v1.jsonl --split dev --model planner-sft-r2 --temperature 0.0 --seed 0 --num-predict 2048 --num-ctx 8192 --run-name old-planner-sft-r2 --mlflow --out reports/eval/old_planner-sft-r2_dev.json
   ```

   Kiểm tra cờ bằng `python -m travel_agent eval --help` trước khi chạy.

**Điều kiện xong:** người dùng đã trả lời hai câu hỏi; có file kết quả cho cả 7 model; `reports/eval/README.md` có thêm 7 dòng, ghi rõ "model cũ, prompt lúc train chưa rõ, chỉ để tham khảo".

### Chặng 1: sửa nền, chốt baseline mới

Nguồn việc: [open-items](2026-11-12-open-items-before-sft.md). Xử lý từng mục trong 10 mục, hoặc ghi lý do bỏ qua ngay trong file đó.

Thứ tự:

1. **Mục 2, model luôn trả 1 ngày.** Thử trước trên 5 request nhiều ngày: schema theo request với `minItems` và `maxItems` của `days` bằng `num_days`. Nếu số ngày đúng thì đưa vào code. Nếu vẫn sai thì nguyên nhân nằm ở prompt; tìm tiếp trước khi sửa.
2. **Mục 1, candidate toàn tỉnh.** Trình người dùng hai phương án (lọc theo bán kính, hoặc theo cụm mỗi ngày) kèm số đo: bao nhiêu cặp candidate vượt 60 phút di chuyển trước và sau khi lọc. Người dùng chọn.
3. **Số candidate tối đa:** chốt 20 theo spec hoặc giữ công thức trong code. Đo token bằng tokenizer Qwen thật cho request dài nhất (3 ngày, pace packed); prompt cộng output phải vừa `max_seq` 2048 (mục 3).
4. **Mục 4 và 5:** bỏ đếm đôi `UNKNOWN_PLACE`/`DUPLICATE_PLACE`; escape `|` trong dòng candidate.
5. **Mục 6 tới 10:** cổng thăng hạng và tái lập.
6. Chạy lại baseline: `dvc repro baseline_eval`, commit `dvc.lock`, `dvc push`. Trong `reports/eval/README.md`, giữ dòng baseline cũ với nhãn "trước khi sửa candidate và schema", thêm dòng baseline mới.

**Điều kiện xong:** cả 10 mục có trạng thái "đã sửa" hoặc "bỏ qua, lý do"; baseline mới đã ghi; trong baseline mới không còn request nào lỗi `day_count_mismatch` do schema; `check.ps1` xanh.

### Chặng 2: solver và dataset SFT

Căn cứ: spec mục 5, 6, 10.2, 10.6, 11.

Sản phẩm:

- `planning/solver.py`: `solve(request, candidates, travel, seed)`, dùng OR-Tools, có timeout, cùng seed cho cùng plan.
- `training/corrupt.py`: mỗi kiểu phá sinh đúng một `IssueCode` mong muốn.
- `build_messages(..., issues=...)` cho mẫu repair. Kiểm tra chữ ký hiện tại trong `planning/prompt.py`; nếu chưa có tham số `issues` thì thêm, và snapshot của prompt sinh plan phải giữ nguyên.
- `scripts/train/build_dataset.py`, `scripts/train/check_dataset.py`, `configs/dataset.yaml`.
- Stage `build_dataset` và `check_dataset` trong `dvc.yaml`.

**Điều kiện xong:**

- Dataset có 3.000 tới 5.000 mẫu, khoảng 85% sinh plan và 15% repair.
- `check_dataset.py` qua cả bốn kiểm tra ở spec mục 10.6: 100% nhãn không có ERROR; không request nào trùng hash với dev hoặc test; mọi mẫu vừa `max_seq` theo tokenizer Qwen thật; phân bố trong ngưỡng.
- `manifest.json` đủ các trường ở spec mục 10.2, gồm số mẫu solver bỏ.
- Đã đọc bằng mắt ít nhất 20 mẫu ngẫu nhiên và ghi nhận xét vào báo cáo chặng.
- Nếu solver bỏ hơn 30% request, dừng và báo người dùng: nhiều khả năng bước chọn candidate còn vấn đề.

### Chặng 3: SFT

Căn cứ: spec mục 7, 10.5, 12, 14.

1. Xác minh tên repo Hugging Face của Qwen3.5 4B và license. Ghi vào `configs/sft.yaml`.
2. Thêm extra `train` vào `pyproject.toml`, khóa phiên bản.
3. **Smoke test:** load 4-bit, train 20 step, đo VRAM đỉnh và số giây mỗi step, merge, convert GGUF, chạy được trong Ollama, trả JSON parse được cho 3 request. Ước tính thời gian run đầy đủ và báo người dùng trước khi chạy.
4. **Run đầy đủ:** siêu tham số khởi điểm ở spec mục 7. Eval dev ở mỗi checkpoint. Giữ checkpoint có `first_pass_valid_rate` cao nhất.
5. Export GGUF, eval dev với `--baseline` trỏ tới file baseline mới, ghi `model_card.json`, thêm stage `sft` và `eval_sft` vào `dvc.yaml`.

**Điều kiện xong:** smoke test qua đủ 5 bước; model SFT có file kết quả dev và qua cổng thăng hạng so với baseline mới; `parse_error_rate` không tăng; `model_card.json` đủ trường ở spec mục 10.5; dòng SFT đã có trong `reports/eval/README.md`.

Nếu SFT không vượt baseline: dừng, đọc 20 output lỗi, báo người dùng nguyên nhân dự đoán kèm bằng chứng. Chưa sang chặng 4.

### Chặng 4: RL

Căn cứ: spec mục 8, 12.

1. `training/reward.py`: hàm thuần theo bảng ở spec mục 8.1, một test cho mỗi dòng của bảng.
2. Chấm reward cho output của baseline và SFT trên dev. Kiểm tra reward xếp hạng đúng: plan hợp lệ điểm cao hơn plan lỗi; plan một stop mỗi ngày bị phạt.
3. **Smoke GRPO** 5 step: đo VRAM đỉnh và số phút mỗi step. OOM sau khi đã giảm `max_completion_length` và số candidate, hoặc chậm hơn 5 phút mỗi step, thì chuyển sang best-of-N (spec mục 8.4).
4. Train. Ở mỗi lần eval dev, theo dõi cùng lúc `first_pass_valid_rate`, `avg_stops_per_day`, `distinct_place_count`, và đọc 10 output.
5. Dừng theo spec mục 8.5: không tăng qua 3 lần eval liên tiếp, hoặc tụt dưới mức SFT, hoặc reward tăng trong khi số stop hay số `place_id` khác nhau sụt.

**Điều kiện xong:** có checkpoint RL tốt nhất với file kết quả dev; `avg_stops_per_day` và `distinct_place_count` không thấp hơn SFT quá 10%; `model_card.json` ghi run cha là adapter SFT nào; stage `rl` và `eval_rl` có trong `dvc.yaml`. Nếu RL không vượt SFT thì ghi đúng như vậy và chọn SFT làm model cuối.

### Chặng 5: so sánh cuối và export

1. Chạy bộ test đúng một lần cho ba mốc: baseline, SFT, SFT+RL. Dùng `--split test --allow-test`.
2. Ghi bảng ba mốc vào `reports/eval/README.md`, kèm số tuyệt đối (ví dụ 21/30) bên cạnh tỉ lệ. Với 30 request, chênh lệch 1 tới 2 request nằm trong nhiễu; ghi rõ điều này.
3. Thêm stage `export`: chỉ chạy khi eval qua cổng. Export GGUF của model thắng, tạo model trong Ollama.
4. `dvc repro` từ đầu trên cây sạch để chứng minh tái lập. `dvc push`.
5. Cập nhật README: cách train lại, cách chạy model cuối.

**Điều kiện xong:** bốn mục ở phần 1 đều đạt.

## 7. Việc phải hỏi người dùng

Dừng và hỏi khi gặp một trong các việc sau. Các việc khác thì tự quyết, ghi lại quyết định và rủi ro nếu sai.

- Merge, push, tạo remote, xóa nhánh.
- Cách lọc candidate theo khu vực (chặng 1).
- Đổi base model, đổi mục tiêu reward, thêm metric chất lượng vào reward.
- Smoke test hỏng sau khi đã làm hết bảng xử lý lỗi ở spec mục 12.
- Run đầy đủ ước tính hơn 12 giờ.
- Solver bỏ hơn 30% request, hoặc SFT không vượt baseline.
- Spec và hiện trạng code mâu thuẫn ở chỗ file này chưa nêu.

## 8. Rủi ro đã biết

- **Reward chỉ đo hợp lệ.** Model có thể học lịch ít điểm, lặp lại vài địa điểm quen. Hai chỉ số `avg_stops_per_day` và `distinct_place_count` là chốt chặn; đọc output bằng mắt ở mỗi lần eval.
- **Giờ mở cửa giả định "mọi ngày"** cho 1.447 trên 1.587 điểm. Lịch qua validator vẫn có thể sai ngoài thực tế. Ghi giới hạn này trong báo cáo cuối.
- **Thời gian di chuyển là ước tính Haversine**, chưa phải đường thật.
- **VRAM 8GB** có thể không đủ cho GRPO. Fallback best-of-N đã thiết kế sẵn.
- **Bộ test chỉ 30 request.** Kết luận cuối cần đi kèm số tuyệt đối.
