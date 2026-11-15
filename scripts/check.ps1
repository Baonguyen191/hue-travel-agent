# Chạy toàn bộ kiểm tra không cần GPU. Dùng trước khi commit; CI chạy cùng các bước này.
$ErrorActionPreference = "Stop"
$py = ".venv\Scripts\python"

& $py -m ruff format --check src tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m mypy src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m dvc stage list
exit $LASTEXITCODE
