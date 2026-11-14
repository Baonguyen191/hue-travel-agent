import json
from collections.abc import Callable

from tests.training.dataset_factories import CHECK, TRAVEL, char_counter, pool, small_build
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Pace
from travel_agent.training.dataset import CheckParams, DatasetSample, SampleKind, ShareBounds
from travel_agent.training.dataset_check import Check, CheckReport, check_dataset
from travel_agent.training.tokens import TokenCounter

Edit = Callable[[DatasetSample], DatasetSample]


def lines(edit: Edit | None = None, index: int = 0) -> list[str]:
    """Dataset nhỏ hợp lệ, dạng dòng JSONL; `edit` sửa mẫu thứ `index` để làm hỏng."""
    samples = list(small_build().samples)
    if edit is not None:
        samples[index] = edit(samples[index])
    return [sample.model_dump_json() for sample in samples]


def run(
    data: list[str],
    *,
    eval_keys: set[str] | None = None,
    counter: TokenCounter | None = char_counter,
    allow_skip: bool = False,
    check: CheckParams = CHECK,
) -> CheckReport:
    return check_dataset(
        data,
        InMemoryPlaceRepository(pool()),
        eval_keys or set(),
        check,
        TRAVEL,
        counter,
        allow_skip_tokens=allow_skip,
    )


def checks(report: CheckReport) -> set[Check]:
    return {failure.check for failure in report.failures}


def first_of(kind: SampleKind) -> int:
    return next(i for i, s in enumerate(small_build().samples) if s.kind is kind)


def with_answer(sample: DatasetSample, content: str) -> DatasetSample:
    messages = [*sample.messages[:2], {"role": "assistant", "content": content}]
    return sample.model_copy(update={"messages": messages})


def test_valid_dataset_passes() -> None:
    report = run(lines())
    assert report.passed, report.failures
    assert report.token_check == "performed"
    assert report.samples == 40
    assert report.max_tokens_seen is not None


def test_invalid_answer_is_caught() -> None:
    def overlap(sample: DatasetSample) -> DatasetSample:
        data = json.loads(sample.messages[-1]["content"])
        stops = data["days"][0]["stops"]
        stops[1]["arrive"] = stops[0]["arrive"]
        return with_answer(sample, json.dumps(data, separators=(",", ":"), ensure_ascii=False))

    report = run(lines(overlap))
    assert not report.passed
    assert Check.ANSWER_INVALID in checks(report)
    assert report.failures[0].line == 1


def test_leaked_eval_request_is_caught() -> None:
    leaked = small_build().samples[3].key
    report = run(lines(), eval_keys={leaked})
    assert checks(report) == {Check.EVAL_LEAK}
    assert report.failures[0].key == leaked


def test_over_long_sample_is_caught() -> None:
    lengths = [char_counter(sample.messages) for sample in small_build().samples]
    limit = sorted(lengths)[-3]  # hai mẫu dài nhất vượt giới hạn
    report = run(lines(), check=CHECK.model_copy(update={"max_tokens": limit}))
    assert checks(report) == {Check.TOO_LONG}
    over = [i + 1 for i, length in enumerate(lengths) if length > limit]
    assert sorted(f.line for f in report.failures if f.line is not None) == over
    assert report.max_tokens_seen == max(lengths)


def test_missing_tokenizer_fails_unless_skipping_is_allowed() -> None:
    missing = run(lines(), counter=None)
    assert not missing.passed
    assert checks(missing) == {Check.TOKENS_NOT_CHECKED}
    assert missing.token_check == "missing"
    assert missing.max_tokens_seen is None

    skipped = run(lines(), counter=None, allow_skip=True)
    assert skipped.passed
    assert skipped.token_check == "skipped"


def test_repair_whose_broken_plan_is_valid_is_caught() -> None:
    def no_error(sample: DatasetSample) -> DatasetSample:
        return sample.model_copy(update={"broken": sample.messages[-1]["content"]})

    report = run(lines(no_error, first_of(SampleKind.REPAIR)))
    assert Check.BROKEN_VALID in checks(report)


def test_repair_with_invalid_answer_is_caught() -> None:
    def bad_answer(sample: DatasetSample) -> DatasetSample:
        assert sample.broken is not None
        return with_answer(sample, sample.broken)

    report = run(lines(bad_answer, first_of(SampleKind.REPAIR)))
    assert Check.ANSWER_INVALID in checks(report)


def test_tampered_prompt_is_caught() -> None:
    def tamper(sample: DatasetSample) -> DatasetSample:
        user = {"role": "user", "content": sample.messages[1]["content"] + "\nthêm"}
        return sample.model_copy(
            update={"messages": [sample.messages[0], user, sample.messages[2]]}
        )

    assert checks(run(lines(tamper))) == {Check.PROMPT_MISMATCH}


def test_non_canonical_answer_is_caught() -> None:
    def spaced(sample: DatasetSample) -> DatasetSample:
        return with_answer(sample, json.dumps(json.loads(sample.messages[-1]["content"])))

    assert checks(run(lines(spaced))) == {Check.ANSWER_FORMAT}


def test_unparseable_answer_and_line_are_caught() -> None:
    def prose(sample: DatasetSample) -> DatasetSample:
        return with_answer(sample, "Đây là lịch trình: {}")

    data = lines(prose)
    data.append("{không phải json")
    found = checks(run(data))
    assert {Check.ANSWER_PARSE, Check.SCHEMA} <= found


def test_key_must_match_request_and_be_unique() -> None:
    def rekey(sample: DatasetSample) -> DatasetSample:
        return sample.model_copy(update={"key": "khac"})

    assert Check.KEY_MISMATCH in checks(run(lines(rekey)))
    data = lines()
    assert Check.DUPLICATE_REQUEST in checks(run([*data, data[0]]))


def test_unknown_candidate_is_caught() -> None:
    def ghost(sample: DatasetSample) -> DatasetSample:
        return sample.model_copy(update={"candidate_ids": [*sample.candidate_ids, "t:ma"]})

    assert Check.UNKNOWN_CANDIDATE in checks(run(lines(ghost)))


def test_skewed_distribution_is_caught() -> None:
    relaxed_only = [
        line
        for line, sample in zip(lines(), small_build().samples, strict=True)
        if sample.request.pace is Pace.RELAXED
    ]
    usual = CHECK.model_copy(update={"distribution": ShareBounds(min_share=0.25, max_share=0.42)})
    report = run(relaxed_only, check=usual)
    assert checks(report) == {Check.DISTRIBUTION}
    messages = " ".join(failure.message for failure in report.failures)
    assert "pace=relaxed" in messages and "pace=packed" in messages


def test_empty_dataset_fails() -> None:
    assert checks(run([])) == {Check.EMPTY}
