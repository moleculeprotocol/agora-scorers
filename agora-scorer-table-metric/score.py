"""
Agora Tabular Scorer

Scores a CSV submission against a CSV evaluation artifact using the canonical
Agora runtime manifest mounted at /input/runtime-manifest.json.

Input:
  /input/runtime-manifest.json
  /input/evaluation/<role>/<filename>
  /input/submission/<role>/<filename>

Output:
  /output/score.json
"""

import json
import math
import sys
from pathlib import Path

SCORER_REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_DIR = SCORER_REPO_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_contract import (
    load_runtime_manifest,
    require_relation,
    resolve_runtime_artifact,
)

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
OUTPUT_PATH = OUTPUT_DIR / "score.json"

NUMERIC_METRICS = {"r2", "rmse", "mae", "pearson", "spearman"}
CLASSIFICATION_METRICS = {"accuracy", "f1"}


def write_result(payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    OUTPUT_PATH.write_text(serialized, encoding="utf-8")


def fail_runtime(message: str) -> None:
    write_result({"ok": False, "score": 0.0, "error": message, "details": {}})
    raise SystemExit(1)


def reject_submission(message: str, details: dict | None = None) -> None:
    write_result(
        {
            "ok": False,
            "score": 0.0,
            "error": message,
            "details": details or {},
        }
    )


def parse_csv(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    lines = text.split("\n")
    header = [col.strip() for col in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values)))
    return rows


def require_csv_slot(slot: dict, slot_label: str) -> dict:
    validator = slot.get("validator")
    if not isinstance(validator, dict):
        fail_runtime(f"Runtime manifest slot {slot_label} is missing validator.")
    if validator.get("kind") != "csv_columns":
        fail_runtime(
            f"Runtime manifest slot {slot_label} must use validator.kind=csv_columns."
        )

    required = validator.get("required")
    id_col = validator.get("record_key")
    value_col = validator.get("value_field")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(col, str) and col for col in required)
    ):
        fail_runtime(f"Runtime manifest slot {slot_label} must declare required columns.")
    if not isinstance(id_col, str) or not id_col:
        fail_runtime(f"Runtime manifest slot {slot_label} must declare validator.record_key.")
    if not isinstance(value_col, str) or not value_col:
        fail_runtime(f"Runtime manifest slot {slot_label} must declare validator.value_field.")
    if id_col not in required or value_col not in required:
        fail_runtime(
            f"Runtime manifest slot {slot_label} must include validator.record_key and validator.value_field in validator.required."
        )
    allow_extra = validator.get("allow_extra", True)
    if not isinstance(allow_extra, bool):
        fail_runtime(f"Runtime manifest slot {slot_label} must use a boolean allow_extra.")

    return {
        "required": required,
        "id": id_col,
        "value": value_col,
        "allow_extra": allow_extra,
    }


def load_runtime_config() -> dict:
    runtime_manifest = load_runtime_manifest(
        input_dir=INPUT_DIR,
        fail_runtime=fail_runtime,
    )
    require_relation(
        runtime_manifest,
        kind="tabular_alignment",
        evaluation_role="reference",
        submission_role="predictions",
        fail_runtime=fail_runtime,
    )
    evaluation_artifact = resolve_runtime_artifact(
        runtime_manifest,
        lane="evaluation",
        role="reference",
        fail_runtime=fail_runtime,
    )
    submission_artifact = resolve_runtime_artifact(
        runtime_manifest,
        lane="submission",
        role="predictions",
        fail_runtime=fail_runtime,
    )
    return {
        "metric": runtime_manifest.get("metric"),
        "submission": require_csv_slot(submission_artifact["slot"], "submission.predictions"),
        "evaluation": require_csv_slot(evaluation_artifact["slot"], "evaluation.reference"),
        "policies": runtime_manifest["policies"],
        "evaluation_path": evaluation_artifact["path"],
        "submission_path": submission_artifact["path"],
    }


def validate_header(
    rows: list[dict[str, str]],
    contract: dict,
    file_label: str,
    runtime_error: bool,
) -> None:
    if not rows:
        message = f"{file_label} is empty."
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)
        raise SystemExit(0)

    present_columns = list(rows[0].keys())
    present_set = set(present_columns)
    missing = [col for col in contract["required"] if col not in present_set]
    if missing:
        message = (
            f"{file_label} must contain required columns: {','.join(contract['required'])}."
        )
        if runtime_error:
            fail_runtime(message)
        reject_submission(
            message,
            {
                "missing_columns": missing,
                "uploaded_columns": present_columns,
            },
        )
        raise SystemExit(0)

    if not contract["allow_extra"]:
        extras = [col for col in present_columns if col not in contract["required"]]
        if extras:
            message = f"{file_label} contains unexpected columns: {','.join(extras)}."
            if runtime_error:
                fail_runtime(message)
            reject_submission(
                message,
                {
                    "unexpected_columns": extras,
                    "uploaded_columns": present_columns,
                },
            )
            raise SystemExit(0)


def build_truth_map(
    truth_rows: list[dict[str, str]],
    contract: dict,
    numeric_values: bool,
) -> tuple[list[str], dict[str, float | str]]:
    truth_ids: list[str] = []
    truth_map: dict[str, float | str] = {}
    id_col = contract["id"]
    value_col = contract["value"]

    for row in truth_rows:
        row_id = row.get(id_col, "")
        if not row_id:
            fail_runtime("Evaluation bundle contains an empty evaluation id.")
        if row_id in truth_map:
            fail_runtime("Evaluation bundle contains duplicate evaluation ids.")

        raw_value = row.get(value_col, "")
        if not raw_value:
            fail_runtime("Evaluation bundle contains an empty target value.")

        if numeric_values:
            try:
                truth_value: float | str = float(raw_value)
            except ValueError:
                fail_runtime(
                    "Evaluation bundle contains a non-numeric target value."
                )
        else:
            truth_value = str(raw_value)

        truth_ids.append(row_id)
        truth_map[row_id] = truth_value

    return truth_ids, truth_map


def summarize_submission(
    sub_rows: list[dict[str, str]],
    submission_csv_contract: dict,
    truth_map: dict[str, float | str],
    policies: dict,
    numeric_values: bool,
) -> tuple[dict[str, float | str], dict]:
    id_col = submission_csv_contract["id"]
    value_col = submission_csv_contract["value"]

    valid_predictions: dict[str, float | str] = {}
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    invalid_value_ids: list[str] = []
    unexpected_ids: list[str] = []

    for row in sub_rows:
        row_id = row.get(id_col, "")
        if not row_id:
            invalid_value_ids.append("")
            continue
        if row_id in seen_ids:
            duplicate_ids.append(row_id)
            if policies["duplicate_id_policy"] == "reject":
                continue
            if row_id in valid_predictions:
                continue
        seen_ids.add(row_id)

        if row_id not in truth_map:
            unexpected_ids.append(row_id)
            continue

        raw_value = row.get(value_col, "")
        if not raw_value:
            invalid_value_ids.append(row_id)
            continue

        if numeric_values:
            try:
                prediction_value: float | str = float(raw_value)
            except ValueError:
                invalid_value_ids.append(row_id)
                continue
        else:
            prediction_value = str(raw_value)

        if row_id not in valid_predictions:
            valid_predictions[row_id] = prediction_value

    missing_truth_ids = [row_id for row_id in truth_map if row_id not in valid_predictions]

    details = {
        "submitted_rows": len(sub_rows),
        "expected_rows": len(truth_map),
        "matched_unique_ids": len(valid_predictions),
        "missing_ids": len(missing_truth_ids),
        "unexpected_ids": len(unexpected_ids),
        "duplicate_ids": len(duplicate_ids),
        "invalid_value_ids": len(invalid_value_ids),
    }

    if duplicate_ids and policies["duplicate_id_policy"] == "reject":
        reject_submission(
            "Submission must not contain duplicate prediction ids.",
            details,
        )
        raise SystemExit(0)

    if invalid_value_ids and policies["invalid_value_policy"] == "reject":
        invalid_message = (
            "Submission contains non-numeric prediction values. Next step: upload a CSV with numeric predictions only."
            if numeric_values
            else "Submission contains empty or invalid label predictions. Next step: upload a CSV with one non-empty prediction for every evaluation id."
        )
        reject_submission(invalid_message, details)
        raise SystemExit(0)

    coverage_policy = policies["coverage_policy"]
    if coverage_policy == "penalize":
        fail_runtime(
            "coverage_policy=penalize is not supported by tabular_v1. Next step: use reject or ignore."
        )
    if coverage_policy == "reject" and (missing_truth_ids or unexpected_ids):
        reject_submission(
            "Submission must include exactly one prediction row for every evaluation id.",
            details,
        )
        raise SystemExit(0)

    if not valid_predictions:
        reject_submission(
            "No valid prediction rows matched the evaluation bundle.",
            details,
        )
        raise SystemExit(0)

    return valid_predictions, details


def rankdata(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 1) / 2
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def normalize_score(metric: str, value: float) -> float:
    if metric == "r2":
        return max(value, 0.0)
    if metric in ("rmse", "mae"):
        return 1.0 / (1.0 + value)
    if metric in ("pearson", "spearman"):
        return max(0.0, min(1.0, (value + 1.0) / 2.0))
    if metric in CLASSIFICATION_METRICS:
        return max(0.0, min(1.0, value))
    fail_runtime(f"Unsupported metric {metric}.")


def compute_macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    labels = sorted(set(y_true) | set(y_pred))
    if not labels:
        return 0.0

    f1_scores: list[float] = []
    for label in labels:
        tp = sum(
            1
            for truth, pred in zip(y_true, y_pred)
            if truth == label and pred == label
        )
        fp = sum(
            1
            for truth, pred in zip(y_true, y_pred)
            if truth != label and pred == label
        )
        fn = sum(
            1
            for truth, pred in zip(y_true, y_pred)
            if truth == label and pred != label
        )
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        if precision + recall == 0:
            f1_scores.append(0.0)
        else:
            f1_scores.append((2 * precision * recall) / (precision + recall))

    return sum(f1_scores) / len(f1_scores)


def main() -> None:
    runtime_config = load_runtime_config()
    metric = str(runtime_config.get("metric") or "r2")
    if metric not in NUMERIC_METRICS | CLASSIFICATION_METRICS:
        fail_runtime(
            f"Unsupported metric {metric}. Next step: choose one of {','.join(sorted(NUMERIC_METRICS | CLASSIFICATION_METRICS))}."
        )

    evaluation_path = runtime_config["evaluation_path"]
    submission_path = runtime_config["submission_path"]

    if not evaluation_path.exists():
        fail_runtime(f"Missing required file: {evaluation_path}")
    if not submission_path.exists():
        fail_runtime(f"Missing required file: {submission_path}")

    truth_rows = parse_csv(evaluation_path)
    sub_rows = parse_csv(submission_path)

    validate_header(
        truth_rows,
        runtime_config["evaluation"],
        "Evaluation bundle",
        runtime_error=True,
    )
    validate_header(
        sub_rows,
        runtime_config["submission"],
        "Submission",
        runtime_error=False,
    )

    numeric_values = metric in NUMERIC_METRICS
    truth_ids, truth_map = build_truth_map(
        truth_rows,
        runtime_config["evaluation"],
        numeric_values=numeric_values,
    )
    valid_predictions, summary = summarize_submission(
        sub_rows,
        runtime_config["submission"],
        truth_map,
        runtime_config["policies"],
        numeric_values=numeric_values,
    )

    if metric in CLASSIFICATION_METRICS:
        y_true: list[str] = []
        y_pred: list[str] = []
        for row_id in truth_ids:
            if row_id not in valid_predictions:
                continue
            y_true.append(str(truth_map[row_id]))
            y_pred.append(str(valid_predictions[row_id]))

        n = len(y_true)
        if n == 0:
            reject_submission(
                "No valid prediction rows matched the evaluation bundle.",
                summary,
            )
            return

        accuracy = sum(1 for truth, pred in zip(y_true, y_pred) if truth == pred) / n
        f1 = compute_macro_f1(y_true, y_pred)
        selected_metric_value = accuracy if metric == "accuracy" else f1
        leaderboard_score = normalize_score(metric, selected_metric_value)

        write_result(
            {
                "ok": True,
                "score": float(round(leaderboard_score, 12)),
                "details": {
                    **summary,
                    "matched_rows": n,
                    "accuracy": float(round(accuracy, 12)),
                    "f1": float(round(f1, 12)),
                    "selected_metric": metric,
                    "selected_metric_value": float(round(selected_metric_value, 12)),
                    "leaderboard_score": float(round(leaderboard_score, 12)),
                },
            }
        )
        return

    y_true: list[float] = []
    y_pred: list[float] = []
    for row_id in truth_ids:
        if row_id not in valid_predictions:
            continue
        y_true.append(float(truth_map[row_id]))
        y_pred.append(float(valid_predictions[row_id]))

    n = len(y_true)
    if n == 0:
        reject_submission(
            "No valid prediction rows matched the evaluation bundle.",
            summary,
        )
        return

    mean_true = sum(y_true) / n
    mean_pred = sum(y_pred) / n

    ss_res = sum((t - p) ** 2 for t, p in zip(y_true, y_pred))
    ss_tot = sum((t - mean_true) ** 2 for t in y_true)

    rmse = math.sqrt(ss_res / n)
    mae = sum(abs(t - p) for t, p in zip(y_true, y_pred)) / n

    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    r2_clamped = max(r2, 0.0)

    std_true = math.sqrt(sum((t - mean_true) ** 2 for t in y_true) / n)
    std_pred = math.sqrt(sum((p - mean_pred) ** 2 for p in y_pred) / n)
    if std_true > 0 and std_pred > 0:
        cov = sum((t - mean_true) * (p - mean_pred) for t, p in zip(y_true, y_pred)) / n
        pearson = cov / (std_true * std_pred)
    else:
        pearson = 0.0

    ranks_true = rankdata(y_true)
    ranks_pred = rankdata(y_pred)
    mean_rank_true = sum(ranks_true) / n
    mean_rank_pred = sum(ranks_pred) / n
    cov_rank = sum(
        (rt - mean_rank_true) * (rp - mean_rank_pred)
        for rt, rp in zip(ranks_true, ranks_pred)
    ) / n
    std_rank_true = math.sqrt(sum((rt - mean_rank_true) ** 2 for rt in ranks_true) / n)
    std_rank_pred = math.sqrt(sum((rp - mean_rank_pred) ** 2 for rp in ranks_pred) / n)
    if std_rank_true > 0 and std_rank_pred > 0:
        spearman = cov_rank / (std_rank_true * std_rank_pred)
    else:
        spearman = 0.0

    metric_values = {
        "r2": float(round(r2, 12)),
        "rmse": float(round(rmse, 12)),
        "mae": float(round(mae, 12)),
        "pearson": float(round(pearson, 12)),
        "spearman": float(round(spearman, 12)),
    }
    selected_metric_value = metric_values[metric]
    leaderboard_score = normalize_score(metric, selected_metric_value)

    write_result(
        {
            "ok": True,
            "score": float(round(leaderboard_score, 12)),
            "details": {
                **summary,
                "matched_rows": n,
                "r2": metric_values["r2"],
                "r2_clamped": float(round(r2_clamped, 12)),
                "rmse": metric_values["rmse"],
                "mae": metric_values["mae"],
                "pearson": metric_values["pearson"],
                "spearman": metric_values["spearman"],
                "selected_metric": metric,
                "selected_metric_value": float(round(selected_metric_value, 12)),
                "leaderboard_score": float(round(leaderboard_score, 12)),
            },
        }
    )


if __name__ == "__main__":
    main()
