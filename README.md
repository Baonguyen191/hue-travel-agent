# Travel Agent: Huế

Dữ liệu địa điểm và công cụ duyệt tay cho LLM lập lịch du lịch chạy offline.
Lộ trình: `docs/superpowers/plans/2026-11-03-hue-planner-roadmap.md`.

## Cài đặt (Windows, Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

**Lưu ý đường dẫn có dấu:** khi project nằm trong thư mục có ký tự tiếng Việt (ví dụ
`OneDrive\Máy tính`), Python 3.11 đọc sai file `.pth` của editable install, nên lệnh
`travel-agent` báo `ModuleNotFoundError`. Có hai cách xử lý:
- Chuyển project sang đường dẫn không dấu, ví dụ `C:\dev\TravelAgent` (khuyến nghị).
- Hoặc đặt `$env:PYTHONPATH="src"` rồi chạy `.venv\Scripts\python -m travel_agent <lệnh>`.

## Dữ liệu

Dữ liệu địa điểm © OpenStreetMap contributors, giấy phép ODbL-1.0.
Chỉ tải một lần, theo nguyên tắc fair-use của Overpass API:

```powershell
travel-agent fetch-osm --out data\raw\osm_hue.json
travel-agent ingest-osm data\raw\osm_hue.json --db data\hue.sqlite
```

## Duyệt tay

```powershell
travel-agent review --db data\hue.sqlite
```

Mở http://127.0.0.1:8765. Server chỉ nghe trên máy này.

**Thao tác:**
- Mỗi địa điểm chọn một trong ba trạng thái: Duyệt (A), Cần sửa (F), Loại (R). Bỏ đánh giá: U.
- Chuyển địa điểm: J/K hoặc ↓/↑.

**Chỉnh sửa:**
- Sửa tên, loại, giờ mở cửa được lưu dưới dạng override. Dữ liệu OSM gốc giữ nguyên.
- Sửa giờ mở cửa phải dùng cú pháp OSM (ví dụ `Mo-Su 07:00-17:30`) và phải ghi nguồn kiểm chứng.

Xuất các địa điểm đã duyệt (đã áp override):

```powershell
travel-agent export-approved --db data\hue.sqlite --out data\hue_places_approved.jsonl
```

## Thêm link nguồn dữ liệu

Cũng trong server `review`, mở http://127.0.0.1:8765/links:
- Dán một hoặc nhiều link (mỗi dòng một link), chọn chủ đề, thêm ghi chú nếu cần.
- Link chỉ được lưu, không tự tải. Xử lý từng nguồn làm sau, sau khi kiểm tra điều khoản và
  giấy phép của nguồn đó.

Liệt kê link chưa xử lý:

```powershell
travel-agent links --db data\hue.sqlite --status new
```

## Độ phủ dữ liệu Huế (OSM, 2026-11-03T16:31:11Z)

| Mục | Số lượng |
|---|---|
| Tổng địa điểm | 785 |
| Có `opening_hours` | 159 |
| restaurant | 309 |
| cafe | 219 |
| religious | 107 |
| historic | 70 |
| attraction | 36 |
| market | 16 |
| park | 16 |
| museum | 12 |

## Eval và MLOps

Thiết kế: `docs/superpowers/specs/2026-11-11-sft-rl-training-design.md`.

Cài thêm công cụ MLOps và thư viện đếm token cho bước kiểm dataset:

```powershell
.venv\Scripts\python -m pip install -e ".[dev,mlops,dataset]"
```

Cấu hình một lần trên mỗi máy (cache DVC, DVC remote và MLflow nằm ngoài OneDrive):

```powershell
New-Item -ItemType Directory -Force C:\dev\travelagent-dvc, C:\dev\travelagent-dvc-cache, C:\dev\travelagent-runs
.venv\Scripts\dvc cache dir --local C:\dev\travelagent-dvc-cache
.venv\Scripts\dvc remote add --local -d localstore C:\dev\travelagent-dvc
```

Chạy pipeline (cần Ollama đang chạy và đã pull model ghi trong `configs/eval.yaml`):

```powershell
.venv\Scripts\Activate.ps1
$env:PYTHONPATH="src"
dvc repro baseline_eval
dvc repro check_dataset
dvc metrics show
```

Dataset SFT (stage `build_dataset` và `check_dataset`, tham số trong `configs/dataset.yaml`):

```powershell
python -m travel_agent build-dataset --config configs/dataset.yaml --db data/hue.sqlite --evalset data/eval/hue_eval_v1.jsonl --out data/sft/hue_sft_v1.jsonl --manifest data/sft/manifest.json
python -m travel_agent check-dataset --config configs/dataset.yaml --db data/hue.sqlite --evalset data/eval/hue_eval_v1.jsonl --dataset data/sft/hue_sft_v1.jsonl --out reports/dataset/check.json
```

- `build-dataset` loại mọi request trùng bộ eval (cả dev và test). Cùng config cho ra cùng file đến từng byte **chỉ khi solver không hết giờ** (`solver_time_limit_s`, 10 giây mỗi request). Máy bận làm vài request hết giờ và bị bỏ, nên danh sách request dùng và cả file đổi theo: lần build lại ngày 2026-11-18 có 19 request hết giờ (bản gốc 0) và md5 khác. Kiểm `timed_out` trong `data/sft/manifest.json`.
- `check-dataset` đếm token bằng tokenizer của `Qwen/Qwen3.5-4B` trong cache Hugging Face (repo và revision ghi trong config). Không nạp được tokenizer thì lệnh hỏng; `--allow-skip-tokens` cho qua nhưng báo cáo ghi `token_check: skipped`. `--tokenizer-dir` trỏ tới thư mục tokenizer khác.

Exit code của `eval`, `build-dataset` và `check-dataset`:

| Mã | Nghĩa |
|---|---|
| 0 | Chạy xong, qua cổng |
| 1 | Crash (traceback của Python) |
| 2 | Sai cách dùng, thiếu file, hoặc báo cáo mốc chạy khác điều kiện nên không so được |
| 3 | `eval` không qua cổng so với mốc |
| 4 | Dataset không đạt: `build-dataset` không đủ mẫu, hoặc `check-dataset` hỏng; hoặc `reward-report` không qua kiểm tra |

- **Bộ eval:** `data/eval/hue_eval_v1.jsonl`, 70 dev và 30 test. Stage `make_evalset` đã đóng băng;
  không sinh lại. Lệnh `eval --split test` cần thêm `--allow-test` và chỉ dùng cho lần so sánh cuối.
- **Tham số:** sửa trong `configs/eval.yaml`, không sửa trong `dvc.yaml`.
- **MLflow:** `.venv\Scripts\mlflow ui --backend-store-uri sqlite:///C:/dev/travelagent-runs/mlflow.db`.
- **Lưu ý:** duyệt tay địa điểm làm đổi `data/hue.sqlite`, nên `dvc repro` sẽ chạy lại eval.
  Chạy `dvc add data/hue.sqlite` sau mỗi đợt duyệt để ghi version dữ liệu mới.

## Model đã train và cách train lại

Kết quả của baseline, SFT và SFT+RL trên dev và test nằm ở `reports/eval/README.md`. Model cuối là
`travel-rl-v1` trong Ollama: 27/70 plan hợp lệ ngay lần đầu trên dev và 16/30 trên test, so với
baseline `qwen3.5:4b` (6/70, 2/30). Model card: `models/sft/sft-v1/model_card.json` và
`models/rl/rl-v1/model_card.json` (`parent` của RL là SFT step 250).

**Chạy model cuối.** Model chỉ cho kết quả đúng khi nhận prompt dựng bằng `build_messages()` và JSON
schema ép số ngày, như lệnh `eval`. Chưa có lệnh lập lịch cho một request đơn lẻ; cách chạy hiện có
là lệnh `eval` với `--model travel-rl-v1` (tham số sinh trong `configs/eval.yaml`).

**Môi trường train** (Windows, GPU 8 GB): venv riêng `C:\dev\venvs\travel` (Python 3.14), cài torch bản
CUDA 13.0 từ `https://download.pytorch.org/whl/cu130` trước, rồi extra `train` trong `pyproject.toml`.
Venv này không cài `travel_agent`: mọi script train chạy với `$env:PYTHONPATH="src"`. Export cần
llama.cpp ở `C:/dev/llama.cpp` (commit ghi trong `models/*/export.json`). Metrics train gửi lên W&B
nếu đã `wandb login` (project trong `configs/sft.yaml: sft.tracking`).

**Stage DVC của phần train** (luôn dùng `--single-item`: không có cờ này, DVC chạy lại mọi stage phía
trên có dep đổi, kể cả train SFT khoảng 30 giờ):

```powershell
$env:PYTHONPATH="src"; $env:PATH="$PWD\.venv\Scripts;$env:PATH"
dvc repro --single-item sft          # SFT QLoRA, configs/sft.yaml (khoảng 17–30 giờ)
dvc repro --single-item export_sft   # GGUF Q4_K_M + model Ollama travel-sft-v1
dvc repro --single-item eval_sft     # eval dev, cổng so với baseline, model card
dvc repro --single-item rl           # train tiếp từ SFT step 250 trên data/rl/rl-v1/round-1.jsonl
dvc repro --single-item export_rl
dvc repro --single-item eval_rl      # cổng so với SFT
```

- **Chọn checkpoint SFT** là việc tay: export và eval từng checkpoint (`export_gguf.py --checkpoint N`),
  ghi step thắng vào `configs/sft.yaml: export.checkpoint`. Xem plan 4.
- **RL bằng best-of-N** (GRPO không vừa GPU 8 GB, xem plan 5): mỗi vòng sinh 4 plan/request qua Ollama
  (`scripts/train/best_of_n.py generate`), giữ plan tốt nhất có reward ≥ 0,9 (`select`), rồi train tiếp
  bằng `sft.py --init-adapter ... --dataset ... --run-dir ...`. Dataset của vòng đã chọn được DVC theo dõi
  ở `data/rl/rl-v1/`, nên stage `rl` không cần sinh lại.
- **Kiểm reward** trên output dev đã có: `python -m travel_agent reward-report --outcomes
  baseline=reports/eval/baseline_dev.outcomes.jsonl --outcomes sft=reports/eval/sft_dev.outcomes.jsonl
  --better sft --worse baseline --out reports/reward/dev_check.json` (exit 4 nếu reward xếp hạng sai).
- **Tái lập:** train trên GPU không tất định hoàn toàn (train lại RL cho 27/70, lần đầu 28/70). Dataset
  SFT phụ thuộc solver có giới hạn thời gian (xem trên). Ngày 2026-11-18 `dvc.lock` được ghi lại bằng
  `dvc commit` sau khi kiểm rằng code đổi không chạm đường chạy mặc định; mọi output dữ liệu và model
  giữ nguyên hash.
- **Run dài** nên chạy qua Task Scheduler (cửa sổ ẩn) để không phụ thuộc VS Code, và cài gói vào venv
  train chỉ khi không có process train nào đang chạy.

## Kiểm thử

```powershell
.venv\Scripts\ruff format src tests
.venv\Scripts\ruff check src tests
.venv\Scripts\mypy src
.venv\Scripts\python -m pytest
```

Hoặc chạy tất cả bằng một lệnh: `powershell -File scripts\check.ps1`.
