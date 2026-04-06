"""
Agora Ranking Scorer

Scores one or more ranked CSV submission relations against CSV evaluation
artifacts using the canonical Agora runtime manifest mounted at
/input/runtime-manifest.json.
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
    aggregate_relation_scores,
    load_runtime_manifest,
    require_relation_plan_template,
    resolve_relation_artifact_sets,
)

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
OUTPUT_PATH = OUTPUT_DIR / "score.json"

SUPPORTED_METRICS = {"spearman", "ndcg"}


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
    raise SystemExit(0)


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
    metric = runtime_manifest["metric"]
    if metric not in SUPPORTED_METRICS:
        fail_runtime(
            f"Unsupported metric {metric}. Next step: choose one of {','.join(sorted(SUPPORTED_METRICS))}."
        )

    template = require_relation_plan_template(
        runtime_manifest,
        kind="tabular_alignment",
        fail_runtime=fail_runtime,
    )
    relation_sets = resolve_relation_artifact_sets(
        runtime_manifest,
        template=template,
        fail_runtime=fail_runtime,
    )

    return {
        "metric": metric,
        "aggregation": template["aggregation"],
        "policies": runtime_manifest["policies"],
        "relation_sets": relation_sets,
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


def build_truth_map(
    truth_rows: list[dict[str, str]],
    contract: dict,
) -> tuple[list[str], dict[str, float]]:
    truth_ids: list[str] = []
    truth_map: dict[str, float] = {}
    id_col = contract["id"]
    value_col = contract["value"]

    for row in truth_rows:
        row_id = row.get(id_col, "")
        if not row_id:
            fail_runtime("Evaluation bundle contains an empty evaluation id.")
        if row_id in truth_map:
            fail_runtime("Evaluation bundle contains duplicate evaluation ids.")
        try:
            truth_value = float(row[value_col])
        except (ValueError, KeyError):
            fail_runtime("Evaluation bundle contains a non-numeric relevance value.")
        truth_ids.append(row_id)
        truth_map[row_id] = truth_value

    return truth_ids, truth_map


def summarize_submission(
    sub_rows: list[dict[str, str]],
    submission_csv_contract: dict,
    truth_map: dict[str, float],
    policies: dict,
) -> tuple[dict[str, float], dict]:
    id_col = submission_csv_contract["id"]
    value_col = submission_csv_contract["value"]

    valid_predictions: dict[str, float] = {}
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

        try:
            pred_val = float(row[value_col])
        except (ValueError, KeyError):
            invalid_value_ids.append(row_id)
            continue

        if row_id not in valid_predictions:
            valid_predictions[row_id] = pred_val

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
            "Submission must not contain duplicate ranking ids.",
            details,
        )

    if invalid_value_ids and policies["invalid_value_policy"] == "reject":
        reject_submission(
            "Submission contains non-numeric ranking scores. Next step: upload a CSV with numeric scores only.",
            details,
        )

    coverage_policy = policies["coverage_policy"]
    if coverage_policy == "penalize":
        fail_runtime(
            "coverage_policy=penalize is not supported by ranking_v1. Next step: use reject or ignore."
        )
    if coverage_policy == "reject" and (missing_truth_ids or unexpected_ids):
        reject_submission(
            "Submission must include exactly one ranking row for every evaluation id.",
            details,
        )

    if not valid_predictions:
        reject_submission(
            "No valid ranking rows matched the evaluation bundle.",
            details,
        )

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


def compute_spearman(y_true: list[float], y_pred: list[float]) -> float:
    n = len(y_true)
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
        return cov_rank / (std_rank_true * std_rank_pred)
    return 0.0


def compute_ndcg(
    truth_ids: list[str],
    truth_map: dict[str, float],
    predictions: dict[str, float],
) -> float:
    ranked_ids = sorted(predictions.keys(), key=lambda row_id: predictions[row_id], reverse=True)
    ideal_ids = sorted(truth_ids, key=lambda row_id: truth_map[row_id], reverse=True)

    def dcg(ids: list[str]) -> float:
        total = 0.0
        for index, row_id in enumerate(ids):
            relevance = truth_map[row_id]
            total += ((2 ** relevance) - 1) / math.log2(index + 2)
        return total

    actual = dcg(ranked_ids)
    ideal = dcg(ideal_ids)
    if ideal <= 0:
        return 0.0
    return actual / ideal


def normalize_score(metric: str, value: float) -> float:
    if metric == "spearman":
        return max(0.0, min(1.0, (value + 1.0) / 2.0))
    if metric == "ndcg":
        return max(0.0, min(1.0, value))
    fail_runtime(f"Unsupported metric {metric}.")


def score_relation(
    relation_artifact_set: dict,
    *,
    metric: str,
    policies: dict,
) -> dict:
    evaluation_artifact = relation_artifact_set["evaluation"][0]
    submission_artifact = relation_artifact_set["submission"][0]
    evaluation_path = evaluation_artifact["path"]
    submission_path = submission_artifact["path"]
    if evaluation_path is None:
        fail_runtime(
            f"Missing required evaluation artifact role {evaluation_artifact['role']}."
        )
    if submission_path is None:
        fail_runtime(
            f"Missing required submission artifact role {submission_artifact['role']}."
        )

    truth_rows = parse_csv(evaluation_path)
    sub_rows = parse_csv(submission_path)
    evaluation_contract = require_csv_slot(
        evaluation_artifact["slot"],
        f"evaluation.{evaluation_artifact['role']}",
    )
    submission_contract = require_csv_slot(
        submission_artifact["slot"],
        f"submission.{submission_artifact['role']}",
    )

    validate_header(
        truth_rows,
        evaluation_contract,
        "Evaluation bundle",
        runtime_error=True,
    )
    validate_header(
        sub_rows,
        submission_contract,
        "Submission",
        runtime_error=False,
    )

    truth_ids, truth_map = build_truth_map(truth_rows, evaluation_contract)
    predictions, summary = summarize_submission(
        sub_rows,
        submission_contract,
        truth_map,
        policies,
    )

    y_true = [truth_map[row_id] for row_id in truth_ids if row_id in predictions]
    y_pred = [predictions[row_id] for row_id in truth_ids if row_id in predictions]
    n = len(y_true)
    if n == 0:
        reject_submission(
            "No valid ranking rows matched the evaluation bundle.",
            summary,
        )

    spearman = compute_spearman(y_true, y_pred)
    ndcg = compute_ndcg(truth_ids, truth_map, predictions)
    selected_metric_value = spearman if metric == "spearman" else ndcg
    leaderboard_score = normalize_score(metric, selected_metric_value)

    return {
        "score": float(round(leaderboard_score, 12)),
        "details": {
            **summary,
            "matched_rows": n,
            "spearman": float(round(spearman, 12)),
            "ndcg": float(round(ndcg, 12)),
            "selected_metric": metric,
            "selected_metric_value": float(round(selected_metric_value, 12)),
            "leaderboard_score": float(round(leaderboard_score, 12)),
        },
    }


def main() -> None:
    runtime_config = load_runtime_config()
    relation_results = []
    relation_scores = []

    for relation_artifact_set in runtime_config["relation_sets"]:
        relation_result = score_relation(
            relation_artifact_set,
            metric=runtime_config["metric"],
            policies=runtime_config["policies"],
        )
        relation_scores.append(relation_result["score"])
        relation_results.append(
            {
                "relation_kind": relation_artifact_set["relation"]["kind"],
                "evaluation_roles": [artifact["role"] for artifact in relation_artifact_set["evaluation"]],
                "submission_roles": [artifact["role"] for artifact in relation_artifact_set["submission"]],
                "score": relation_result["score"],
                "details": relation_result["details"],
            }
        )

    aggregated_score = aggregate_relation_scores(
        relation_scores,
        aggregation=runtime_config["aggregation"],
        fail_runtime=fail_runtime,
    )
    write_result(
        {
            "ok": True,
            "score": float(round(aggregated_score, 12)),
            "details": {
                "aggregation": runtime_config["aggregation"],
                "relation_count": len(relation_results),
                "selected_metric": runtime_config["metric"],
                "selected_metric_value": float(round(aggregated_score, 12)),
                "leaderboard_score": float(round(aggregated_score, 12)),
                "relation_scores": relation_results,
            },
        }
    )


if __name__ == "__main__":
    main()
