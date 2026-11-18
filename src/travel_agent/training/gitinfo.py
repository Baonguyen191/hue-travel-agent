"""Thông tin git và pipeline DVC cho báo cáo: commit đang chạy, có bị sửa chưa commit không.

Tách khỏi `commands.py` để `scripts/train/write_model_card.py` chỉ kéo theo module nhỏ này, không
kéo theo toàn bộ lệnh CLI (và các module mà lệnh plan dùng).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

import yaml

DVC_LOCK = "dvc.lock"
DVC_PIPELINE = "dvc.yaml"


def pipeline_outputs(dvc_yaml: Path) -> set[str]:
    """Path (tương đối gốc repo) mà pipeline DVC tự ghi: outs, metrics, plots, và dvc.lock.

    `dvc repro` xóa output của stage trước khi chạy và ghi lại dvc.lock sau mỗi stage, nên các
    file này đổi giữa chừng một lần chạy mà code không đổi.
    """
    found = {DVC_LOCK}
    if not dvc_yaml.is_file():
        return found
    stages = (yaml.safe_load(dvc_yaml.read_text(encoding="utf-8")) or {}).get("stages") or {}
    for stage in stages.values():
        for key in ("outs", "metrics", "plots"):
            for entry in stage.get(key) or []:
                found.add(entry if isinstance(entry, str) else next(iter(entry)))
    return found


def _changed_paths(porcelain_z: str) -> list[str]:
    """Path trong output `git status --porcelain -z`; đổi tên thì lấy cả path cũ."""
    entries = porcelain_z.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            paths.append(entries[index])  # path gốc đứng ngay sau
            index += 1
    return paths


def _ignored(path: str, ignored: set[str]) -> bool:
    return any(path == item or path.startswith(item.rstrip("/") + "/") for item in ignored)


def current_commit(own_outputs: Iterable[Path] = ()) -> str:
    """Commit đang chạy; thêm `-dirty` khi file đã track có thay đổi chưa commit.

    Không tính: file chưa track, output của pipeline DVC (kể cả dvc.lock) và `own_outputs` là các
    file lệnh này sắp ghi. Những file đó là dữ liệu do lần chạy sinh ra, không phải code đang chạy.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--untracked-files=no"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    commit = head.stdout.strip()
    root = Path(top.stdout.strip()).resolve()
    ignored = pipeline_outputs(root / DVC_PIPELINE)
    for path in own_outputs:
        try:
            ignored.add(path.resolve().relative_to(root).as_posix())
        except ValueError:
            continue  # file nằm ngoài repo: git không theo dõi
    dirty = [path for path in _changed_paths(status.stdout) if not _ignored(path, ignored)]
    return f"{commit}-dirty" if dirty else commit
