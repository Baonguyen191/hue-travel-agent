"""Ghi tham số và metric của một lần eval vào MLflow. Import mlflow trễ: chỉ cần khi ghi."""

from __future__ import annotations

import os
from collections.abc import Mapping

from travel_agent.training.metrics import EvalSummary

# Ngoài OneDrive: store không bị đồng bộ và tránh đường dẫn có dấu.
DEFAULT_TRACKING_URI = "sqlite:///C:/dev/travelagent-runs/mlflow.db"
EXPERIMENT = "hue-planner"


def numeric_metrics(summary: EvalSummary) -> dict[str, float]:
    metrics = {
        "n": float(summary.n),
        "first_pass_valid_rate": summary.first_pass_valid_rate,
        "parse_error_rate": summary.parse_error_rate,
        "unknown_place_rate": summary.unknown_place_rate,
        "avg_stops_per_day": summary.avg_stops_per_day,
        "distinct_place_count": float(summary.distinct_place_count),
        "latency_p50_s": summary.latency_p50_s,
    }
    for code, count in summary.issue_code_distribution.items():
        metrics[f"issue.{code}"] = float(count)
    return metrics


def log_eval_run(
    run_name: str, params: Mapping[str, str | int | float], summary: EvalSummary
) -> None:
    import mlflow

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(dict(params))
        mlflow.log_metrics(numeric_metrics(summary))
