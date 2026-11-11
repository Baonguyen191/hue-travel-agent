import sys
import types
from typing import Any

import pytest

from travel_agent.training.metrics import EvalSummary
from travel_agent.training.tracking import log_eval_run, numeric_metrics

SUMMARY = EvalSummary(
    n=10,
    first_pass_valid_rate=0.4,
    parse_error_rate=0.1,
    unknown_place_rate=0.05,
    avg_stops_per_day=4.5,
    distinct_place_count=30,
    latency_p50_s=12.0,
    issue_code_distribution={"stop_overlap": 3},
)


def test_numeric_metrics_flattens_issue_codes() -> None:
    assert numeric_metrics(SUMMARY) == {
        "n": 10.0,
        "first_pass_valid_rate": 0.4,
        "parse_error_rate": 0.1,
        "unknown_place_rate": 0.05,
        "avg_stops_per_day": 4.5,
        "distinct_place_count": 30.0,
        "latency_p50_s": 12.0,
        "issue.stop_overlap": 3.0,
    }


class FakeRun:
    def __enter__(self) -> "FakeRun":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_log_eval_run_sends_params_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    def start_run(run_name: str) -> FakeRun:
        calls.append(("run", run_name))
        return FakeRun()

    fake = types.SimpleNamespace(
        set_tracking_uri=lambda uri: calls.append(("uri", uri)),
        set_experiment=lambda name: calls.append(("experiment", name)),
        start_run=start_run,
        log_params=lambda params: calls.append(("params", params)),
        log_metrics=lambda metrics: calls.append(("metrics", metrics)),
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "sqlite:///x.db")

    log_eval_run("baseline", {"model": "m"}, SUMMARY)

    assert calls == [
        ("uri", "sqlite:///x.db"),
        ("experiment", "hue-planner"),
        ("run", "baseline"),
        ("params", {"model": "m"}),
        ("metrics", numeric_metrics(SUMMARY)),
    ]
