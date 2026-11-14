from pathlib import Path

import pytest

from travel_agent.training.dataset import load_config
from travel_agent.training.tokens import (
    CHAT_TEMPLATE_FILE,
    TOKENIZER_FILE,
    TokenizerUnavailable,
    hf_hub_cache,
    hf_snapshot_dir,
    load_chat_token_counter,
)

REPO = Path(__file__).parents[2]
MESSAGES = [
    {"role": "system", "content": "luật"},
    {"role": "user", "content": "yêu cầu"},
    {"role": "assistant", "content": "{}"},
]


def test_snapshot_dir_follows_the_hugging_face_cache_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))
    assert hf_hub_cache() == tmp_path / "home" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert hf_snapshot_dir("Org/Model-1", "abc") == (
        tmp_path / "hub" / "models--Org--Model-1" / "snapshots" / "abc"
    )


def test_missing_files_raise_instead_of_guessing(tmp_path: Path) -> None:
    with pytest.raises(TokenizerUnavailable):
        load_chat_token_counter(tmp_path)


def test_counter_renders_the_chat_template_then_counts(tmp_path: Path) -> None:
    tokenizers = pytest.importorskip("tokenizers")
    vocab = {"[UNK]": 0, "<s>": 1, "</s>": 2}
    model = tokenizers.models.WordLevel(vocab, unk_token="[UNK]")
    tokenizer = tokenizers.Tokenizer(model)
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(tmp_path / TOKENIZER_FILE))
    template = (
        "{% for m in messages %}<s> {{ m.role }} {{ m.content }} </s> {% endfor %}"
        "{% if add_generation_prompt %}MỞ{% endif %}{% if enable_thinking %}NGHĨ{% endif %}"
    )
    (tmp_path / CHAT_TEMPLATE_FILE).write_text(template, encoding="utf-8")
    count = load_chat_token_counter(tmp_path)
    # 3 message x (<s> role nội-dung... </s>): "yêu cầu" là 2 từ. Không thêm prompt sinh.
    assert count(MESSAGES) == 3 * 4 + 1


def configured_qwen() -> Path:
    tokenizer = load_config(REPO / "configs" / "dataset.yaml").check.tokenizer
    path = hf_snapshot_dir(tokenizer.repo, tokenizer.revision)
    if not (path / TOKENIZER_FILE).is_file():
        pytest.skip(f"chưa tải tokenizer {tokenizer.repo} về cache")
    pytest.importorskip("tokenizers")
    return path


def test_configured_tokenizer_renders_the_qwen_chat_format_with_thinking_off() -> None:
    """Chuỗi render phải đúng dạng Qwen: đáp án nằm sau khối think rỗng, kết thúc bằng im_end."""
    from tokenizers import Tokenizer

    path = configured_qwen()
    count = load_chat_token_counter(path)
    expected = (
        "<|im_start|>system\nluật<|im_end|>\n<|im_start|>user\nyêu cầu<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n{}<|im_end|>\n"
    )
    tokenizer = Tokenizer.from_file(str(path / TOKENIZER_FILE))
    assert count(MESSAGES) == len(tokenizer.encode(expected, add_special_tokens=False).ids)
    assert tokenizer.token_to_id("<|im_end|>") == 248046  # cùng eos với GGUF của qwen3.5:4b
