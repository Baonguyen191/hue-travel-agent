from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from travel_agent.training.chat import TOKENIZER_FILE, ChatTokenizer
from travel_agent.training.dataset import DatasetSample, load_config
from travel_agent.training.sft_data import (
    END_OF_TURN,
    IGNORE_INDEX,
    EncodingError,
    encode_lines,
    encode_messages,
)
from travel_agent.training.tokens import hf_snapshot_dir, load_chat_token_counter

REPO = Path(__file__).parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "sft_samples.jsonl"  # 3 dòng thật của hue_sft_v1.jsonl
MESSAGES = [
    {"role": "system", "content": "S"},
    {"role": "user", "content": "U"},
    {"role": "assistant", "content": "{}"},
]


class CharChat:
    """Chat giả: mỗi ký tự một token, để kiểm vị trí mask bằng mắt."""

    def __init__(self, trailer: str = "\n") -> None:
        self.trailer = trailer

    def render(self, messages: Sequence[Mapping[str, str]], *, add_generation_prompt: bool) -> str:
        head = "".join(f"<{m['role']}>{m['content']}" for m in messages if m["role"] != "assistant")
        if add_generation_prompt:
            return head + "<a>"
        return head + "<a>" + messages[-1]["content"] + END_OF_TURN + self.trailer

    def encode(self, text: str) -> list[int]:
        return [ord(char) for char in text]


def test_only_the_answer_and_end_of_turn_are_trained() -> None:
    chat = CharChat()
    encoded = encode_messages(MESSAGES, chat, max_seq=1000)  # type: ignore[arg-type]
    prompt = len("<system>S<user>U<a>")
    trained = len("{}" + END_OF_TURN)
    assert encoded.labels[:prompt] == [IGNORE_INDEX] * prompt
    assert encoded.labels[prompt : prompt + trained] == encoded.input_ids[prompt : prompt + trained]
    assert encoded.labels[prompt + trained :] == [IGNORE_INDEX]  # "\n" sau <|im_end|>
    assert encoded.trained_tokens == trained


def test_train_text_must_extend_the_generation_prompt() -> None:
    with pytest.raises(EncodingError):
        encode_messages(MESSAGES, CharChat(trailer=""), max_seq=1000)  # type: ignore[arg-type]


def test_too_long_sample_is_refused() -> None:
    with pytest.raises(EncodingError):
        encode_messages(MESSAGES, CharChat(), max_seq=10)  # type: ignore[arg-type]


def test_roles_must_be_system_user_assistant() -> None:
    with pytest.raises(EncodingError):
        encode_messages(MESSAGES[1:], CharChat(), max_seq=1000)  # type: ignore[arg-type]


def snapshot_dir() -> Path:
    tokenizer = load_config(REPO / "configs" / "dataset.yaml").check.tokenizer
    path = hf_snapshot_dir(tokenizer.repo, tokenizer.revision)
    if not (path / TOKENIZER_FILE).is_file():
        pytest.skip(f"chưa tải tokenizer {tokenizer.repo} về cache")
    pytest.importorskip("tokenizers")
    return path


def fixture_samples() -> list[DatasetSample]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [DatasetSample.model_validate_json(line) for line in lines]


def test_real_samples_mask_exactly_the_answer() -> None:
    path = snapshot_dir()
    chat = ChatTokenizer.from_dir(path)
    count = load_chat_token_counter(path)
    samples = fixture_samples()
    encoded = encode_lines(FIXTURE.read_text(encoding="utf-8").splitlines(), chat, max_seq=4096)
    assert {sample.kind.value for sample in samples} == {"generate", "repair"}
    for sample, item in zip(samples, encoded, strict=True):
        # Cùng số token mà check-dataset đã đếm khi so với max_tokens.
        assert len(item.input_ids) == count(sample.messages)
        trained = [token for token in item.labels if token != IGNORE_INDEX]
        assert chat.decode(trained) == sample.messages[-1]["content"] + END_OF_TURN
        prompt = chat.render(sample.messages[:-1], add_generation_prompt=True)
        assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
        assert chat.decode(item.input_ids).startswith(prompt)


def test_render_matches_transformers_apply_chat_template() -> None:
    """Chạy bằng venv train (có transformers); venv project bỏ qua."""
    path = snapshot_dir()
    transformers = pytest.importorskip("transformers")
    reference = transformers.AutoTokenizer.from_pretrained(str(path))
    chat = ChatTokenizer.from_dir(path)
    for sample in fixture_samples():
        for messages, generation in ((sample.messages[:-1], True), (sample.messages, False)):
            expected = reference.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=generation, enable_thinking=False
            )
            text = chat.render(messages, add_generation_prompt=generation)
            assert text == expected
            assert chat.encode(text) == reference(text, add_special_tokens=False)["input_ids"]
