"""Lệnh export GGUF và Modelfile Ollama cho model SFT. Hàm thuần: chỉ dựng lệnh và văn bản.

Script `scripts/train/export_gguf.py` chạy các lệnh này. Model SFT trong Ollama phải khác
`qwen3.5:4b` chỉ ở trọng số: Modelfile chép nguyên từ model mẫu, chỉ thay dòng `FROM` trỏ tới
trọng số text.
"""

from __future__ import annotations

from pathlib import Path

CONVERT_SCRIPT = "convert_hf_to_gguf.py"
QUANTIZE_EXE = Path("build") / "bin" / "llama-quantize.exe"
CONVERT_OUTTYPE = "bf16"  # giữ đúng dtype của trọng số merge, quantize ở bước sau


def convert_command(
    python: Path, llama_cpp_dir: Path, merged_dir: Path, out_gguf: Path
) -> list[str]:
    return [
        str(python),
        str(llama_cpp_dir / CONVERT_SCRIPT),
        str(merged_dir),
        "--outfile",
        str(out_gguf),
        "--outtype",
        CONVERT_OUTTYPE,
    ]


def quantize_command(
    llama_cpp_dir: Path, source: Path, out_gguf: Path, quantization: str
) -> list[str]:
    return [str(llama_cpp_dir / QUANTIZE_EXE), str(source), str(out_gguf), quantization]


def _directive_indices(lines: list[str]) -> list[int]:
    """Chỉ số các dòng lệnh của Modelfile, bỏ qua nội dung trong khối `\"\"\"...\"\"\"`.

    `TEMPLATE`, `SYSTEM`, `LICENSE` có thể chứa văn bản nhiều dòng; một dòng trong đó bắt đầu bằng
    chữ FROM không phải lệnh FROM.
    """
    indices: list[int] = []
    inside = False
    for index, line in enumerate(lines):
        if not inside:
            indices.append(index)
        if line.count('"""') % 2 == 1:
            inside = not inside
    return indices


def from_lines(modelfile: str) -> list[str]:
    """Đường dẫn trong các dòng lệnh `FROM` của Modelfile, theo thứ tự."""
    lines = modelfile.splitlines()
    return [lines[i][5:].strip() for i in _directive_indices(lines) if lines[i].startswith("FROM ")]


def swap_model_from(modelfile: str, base_weights: str, new_gguf: Path) -> str:
    """Thay đúng dòng `FROM <base_weights>` bằng `FROM <new_gguf>`; mọi dòng khác giữ nguyên.

    Báo `ValueError` nếu không có hoặc có nhiều hơn một dòng như vậy, để không lặng lẽ tạo ra
    model khác model mẫu ở chỗ khác ngoài trọng số.
    """
    target = f"FROM {base_weights}"
    lines = modelfile.splitlines(keepends=True)
    hits = [i for i in _directive_indices(lines) if lines[i].rstrip("\r\n") == target]
    if len(hits) != 1:
        raise ValueError(f"cần đúng một dòng '{target}', thấy {len(hits)}")
    index = hits[0]
    ending = lines[index][len(target) :]
    lines[index] = f"FROM {new_gguf}{ending}"
    return "".join(lines)
