"""Biến mẫu dataset SFT thành `input_ids` và `labels` cho trainer. Không cần torch.

Loss chỉ tính trên đáp án của assistant và token `<|im_end|>` kết thúc nó: mọi token của system,
user và phần mở đầu `<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n` có label -100. Phần
trước đáp án phải đúng bằng prompt lúc sinh (render với `add_generation_prompt=True`), nên model
học tiếp đúng từ chỗ nó sẽ thấy lúc chạy. Sai điều kiện nào thì báo `EncodingError`, không sửa hộ.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from travel_agent.training.chat import ChatTokenizer
from travel_agent.training.dataset import DatasetSample

IGNORE_INDEX = -100  # label bị bỏ qua khi tính loss (quy ước của transformers)
END_OF_TURN = "<|im_end|>"
ROLES = ("system", "user", "assistant")


class EncodingError(ValueError):
    """Mẫu không tokenize được đúng cách; dataset hoặc chat template có vấn đề."""


@dataclass(frozen=True)
class EncodedSample:
    input_ids: list[int]
    labels: list[int]

    @property
    def trained_tokens(self) -> int:
        return sum(label != IGNORE_INDEX for label in self.labels)


def encode_messages(
    messages: Sequence[Mapping[str, str]], chat: ChatTokenizer, max_seq: int
) -> EncodedSample:
    roles = tuple(message.get("role") for message in messages)
    if roles != ROLES:
        raise EncodingError(f"vai trò {roles}, cần {ROLES}")
    answer = messages[-1]["content"]
    prompt_text = chat.render(messages[:-1], add_generation_prompt=True)
    full_text = chat.render(messages, add_generation_prompt=False)
    trained_text = prompt_text + answer + END_OF_TURN
    if full_text != trained_text + "\n":
        raise EncodingError("chuỗi train không bằng prompt lúc sinh + đáp án + <|im_end|>")

    full_ids = chat.encode(full_text)
    prompt_ids = chat.encode(prompt_text)
    trained_ids = chat.encode(trained_text)
    for name, ids in (("prompt", prompt_ids), ("đáp án", trained_ids)):
        if full_ids[: len(ids)] != ids:
            raise EncodingError(f"token của phần {name} không phải tiền tố của token cả mẫu")
    if len(full_ids) > max_seq:
        raise EncodingError(f"{len(full_ids)} token > max_seq {max_seq}")

    start, end = len(prompt_ids), len(trained_ids)
    labels = [IGNORE_INDEX] * start + full_ids[start:end] + [IGNORE_INDEX] * (len(full_ids) - end)
    return EncodedSample(input_ids=full_ids, labels=labels)


def encode_lines(lines: Iterable[str], chat: ChatTokenizer, max_seq: int) -> list[EncodedSample]:
    """Tokenize mọi dòng JSONL của dataset; dòng lỗi báo kèm số dòng."""
    encoded: list[EncodedSample] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        sample = DatasetSample.model_validate_json(line)
        try:
            encoded.append(encode_messages(sample.messages, chat, max_seq))
        except EncodingError as exc:
            raise EncodingError(f"dòng {line_no} ({sample.key}): {exc}") from exc
    return encoded
