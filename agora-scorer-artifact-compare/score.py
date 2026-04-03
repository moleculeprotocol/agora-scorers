"""
Agora Exact-Match Scorer

Supports deterministic exact-match scoring for:
  - CSV answer artifacts compared against a reference CSV
  - JSON answer artifacts compared against a reference JSON document
  - structured JSON records validated against a hidden structured-record rubric
  - arbitrary file artifacts compared byte-for-byte against a reference artifact

Input:
  /input/runtime-manifest.json
  /input/evaluation/<role>/<filename>
  /input/submission/<role>/<filename>

Output:
  /output/score.json
"""

import csv
import json
import math
import os
import sys
from pathlib import Path

SCORER_REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_DIR = SCORER_REPO_ROOT / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_contract import (
    find_relation,
    load_runtime_manifest,
    require_relation,
    resolve_runtime_artifact,
)

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
OUTPUT_PATH = OUTPUT_DIR / "score.json"


def deterministic_json_write(payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    OUTPUT_PATH.write_text(serialized, encoding="utf-8")


def fail_runtime(message: str) -> None:
    deterministic_json_write({"ok": False, "score": 0.0, "error": message, "details": {}})
    raise SystemExit(1)


def reject_submission(message: str, details: dict | None = None) -> None:
    deterministic_json_write(
        {
            "ok": False,
            "score": 0.0,
            "error": message,
            "details": details or {},
        }
    )
    raise SystemExit(0)


def require_csv_slot(slot: dict, slot_label: str) -> None:
    validator = slot.get("validator")
    if not isinstance(validator, dict):
        fail_runtime(f"Runtime manifest slot {slot_label} is missing validator.")
    if validator.get("kind") != "csv_columns":
        fail_runtime(
            f"Runtime manifest slot {slot_label} must use validator.kind=csv_columns."
        )
    required = validator.get("required")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(column, str) and column for column in required)
    ):
        fail_runtime(
            f"Runtime manifest slot {slot_label} must declare validator.required."
        )


def resolve_exact_match_mode(evaluation_slot: dict, submission_slot: dict) -> str:
    evaluation_kind = evaluation_slot.get("validator", {}).get("kind")
    submission_kind = submission_slot.get("validator", {}).get("kind")
    if evaluation_kind != submission_kind:
        fail_runtime(
            "Runtime manifest exact_match roles must use matching validator kinds."
        )

    if evaluation_kind == "csv_columns":
        require_csv_slot(evaluation_slot, "evaluation.reference")
        require_csv_slot(submission_slot, "submission.answer")
        return "csv_exact_match"

    if evaluation_kind in {"json_document", "json_schema"}:
        return "json_exact_match"

    if evaluation_kind == "none":
        return "byte_exact_match"

    fail_runtime(
        "official exact-match scorer supports csv_columns, json_document/json_schema, and none validators only."
    )


def load_runtime_config() -> dict:
    runtime_manifest = load_runtime_manifest(
        input_dir=INPUT_DIR,
        fail_runtime=fail_runtime,
    )
    metric = runtime_manifest.get("metric", "custom")

    structured_relation = find_relation(
        runtime_manifest,
        kind="structured_validation",
        evaluation_role="rubric",
        submission_role="record",
    )
    exact_match_relation = None if structured_relation else find_relation(
        runtime_manifest,
        kind="exact_match",
        evaluation_role="reference",
        submission_role="answer",
    )

    if structured_relation is not None:
        if metric != "validation_score":
            fail_runtime(
                "official structured-record scorer requires metric=validation_score."
            )
        evaluation_artifact = resolve_runtime_artifact(
            runtime_manifest,
            lane="evaluation",
            role="rubric",
            fail_runtime=fail_runtime,
        )
        submission_artifact = resolve_runtime_artifact(
            runtime_manifest,
            lane="submission",
            role="record",
            fail_runtime=fail_runtime,
        )
        evaluation_kind = evaluation_artifact["slot"].get("validator", {}).get("kind")
        submission_kind = submission_artifact["slot"].get("validator", {}).get("kind")
        if evaluation_kind not in {"json_document", "json_schema"}:
            fail_runtime(
                "official structured-record scorer requires rubric validator.kind=json_document or json_schema."
            )
        if submission_kind not in {"json_document", "json_schema"}:
            fail_runtime(
                "official structured-record scorer requires record validator.kind=json_document or json_schema."
            )
        comparison_kind = "structured_validation"
    elif exact_match_relation is not None:
        if metric != "exact_match":
            fail_runtime("official exact-match scorer requires metric=exact_match.")
        evaluation_artifact = resolve_runtime_artifact(
            runtime_manifest,
            lane="evaluation",
            role="reference",
            fail_runtime=fail_runtime,
        )
        submission_artifact = resolve_runtime_artifact(
            runtime_manifest,
            lane="submission",
            role="answer",
            fail_runtime=fail_runtime,
        )
        comparison_kind = resolve_exact_match_mode(
            evaluation_artifact["slot"],
            submission_artifact["slot"],
        )
    else:
        fail_runtime(
            "Runtime manifest must declare either exact_match(reference, answer) or structured_validation(rubric, record)."
        )

    return {
        "comparison_kind": comparison_kind,
        "evaluation_path": evaluation_artifact["path"],
        "submission_path": submission_artifact["path"],
    }


def read_csv_rows(path: Path, label: str, runtime_error: bool) -> list[dict[str, str]]:
    if not path.exists():
        message = f"Missing required file: {path}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception as error:
        message = f"{label} is not valid CSV data: {error}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)
    raise AssertionError("unreachable")


def is_empty_csv(rows: list[dict[str, str]]) -> bool:
    return len(rows) == 0


def is_numeric_value(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def compare_csv_exact_match(evaluation_path: Path, submission_path: Path) -> None:
    tolerance = float(os.getenv("AGORA_TOLERANCE", "0.001"))
    truth = read_csv_rows(evaluation_path, "Evaluation bundle", True)
    submission = read_csv_rows(submission_path, "Submission", False)

    if is_empty_csv(truth):
        deterministic_json_write(
            {
                "ok": True,
                "details": {
                    "comparison_kind": "csv_exact_match",
                    "comparable_rows": 0,
                    "mismatched_row_penalty": 0,
                    "selected_metric": "exact_match",
                    "selected_metric_value": 1.0,
                    "tolerance": tolerance,
                },
                "matched_rows": 0,
                "score": 1.0,
                "total_rows": 0,
            }
        )
        return

    truth_columns = list(truth[0].keys())
    submission_columns = list(submission[0].keys()) if submission else []
    missing_columns = [column for column in truth_columns if column not in submission_columns]
    if missing_columns:
        reject_submission(
            f"Submission missing required columns: {','.join(missing_columns)}",
            {"missing_columns": missing_columns},
        )

    total_rows = len(truth)
    comparable_rows = min(len(truth), len(submission))

    matched_rows = 0
    for row_index in range(comparable_rows):
        truth_row = truth[row_index]
        submission_row = submission[row_index]
        row_matches = True
        for column in truth_columns:
            truth_value = truth_row.get(column)
            submission_value = submission_row.get(column)
            if truth_value == "" and submission_value == "":
                continue
            if is_numeric_value(truth_value) and is_numeric_value(submission_value):
                if not math.isclose(
                    float(truth_value),
                    float(submission_value),
                    abs_tol=tolerance,
                    rel_tol=0.0,
                ):
                    row_matches = False
                    break
            else:
                if str(truth_value) != str(submission_value):
                    row_matches = False
                    break
        if row_matches:
            matched_rows += 1

    mismatched_row_penalty = abs(len(truth) - len(submission))
    denominator = total_rows if total_rows > 0 else max(len(submission), 1)
    score = max(matched_rows - mismatched_row_penalty, 0) / denominator

    deterministic_json_write(
        {
            "ok": True,
            "details": {
                "comparison_kind": "csv_exact_match",
                "comparable_rows": comparable_rows,
                "mismatched_row_penalty": mismatched_row_penalty,
                "selected_metric": "exact_match",
                "selected_metric_value": float(round(score, 12)),
                "tolerance": tolerance,
            },
            "matched_rows": matched_rows,
            "score": float(round(score, 12)),
            "total_rows": int(total_rows),
        }
    )


def read_json_document(path: Path, label: str, runtime_error: bool):
    if not path.exists():
        message = f"Missing required file: {path}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        message = f"{label} is not valid JSON: {error.msg}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)

    raise AssertionError("unreachable")


def compare_json_exact_match(evaluation_path: Path, submission_path: Path) -> None:
    truth = read_json_document(evaluation_path, "Evaluation bundle", True)
    submission = read_json_document(submission_path, "Submission", False)
    matched = truth == submission
    score = 1.0 if matched else 0.0

    deterministic_json_write(
        {
            "ok": True,
            "details": {
                "comparison_kind": "json_exact_match",
                "selected_metric": "exact_match",
                "selected_metric_value": score,
            },
            "matched_rows": 1 if matched else 0,
            "score": score,
            "total_rows": 1,
        }
    )


def normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry.strip() for entry in value if isinstance(entry, str) and entry.strip()]


def has_present_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return len(value.strip()) > 0
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def parse_allowed_string_values(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for field, options in value.items():
        if not isinstance(field, str):
            continue
        normalized_options = normalize_string_list(options)
        if normalized_options:
            normalized[field] = normalized_options
    return normalized


def parse_structured_record_rubric(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        fail_runtime("Structured record rubric must be a JSON object.")

    required_fields = normalize_string_list(
        document.get("required_fields") or document.get("required_sections")
    )
    non_empty_array_fields = normalize_string_list(
        document.get("non_empty_array_fields")
    )
    allowed_string_values = parse_allowed_string_values(
        document.get("allowed_string_values")
    )

    checks_total = (
        len(required_fields)
        + len(non_empty_array_fields)
        + len(allowed_string_values)
    )
    if checks_total == 0:
        fail_runtime(
            "Structured record rubric must declare at least one deterministic validation rule using required_fields, required_sections, non_empty_array_fields, or allowed_string_values."
        )

    return {
        "required_fields": required_fields,
        "non_empty_array_fields": non_empty_array_fields,
        "allowed_string_values": allowed_string_values,
    }


def compare_structured_record_validation(
    evaluation_path: Path, submission_path: Path
) -> None:
    rubric_document = read_json_document(evaluation_path, "Evaluation bundle", True)
    submission = read_json_document(submission_path, "Submission", False)
    if not isinstance(submission, dict):
        reject_submission(
            "Submission must be a JSON object.",
            {"comparison_kind": "structured_validation"},
        )

    rubric = parse_structured_record_rubric(rubric_document)
    required_fields = rubric["required_fields"]
    non_empty_array_fields = rubric["non_empty_array_fields"]
    allowed_string_values = rubric["allowed_string_values"]

    checks_passed = 0
    failed_checks: list[str] = []

    for field in required_fields:
        if has_present_value(submission.get(field)):
            checks_passed += 1
        else:
            failed_checks.append(f"missing_or_empty:{field}")

    for field in non_empty_array_fields:
        value = submission.get(field)
        if isinstance(value, list) and len(value) > 0:
            checks_passed += 1
        else:
            failed_checks.append(f"array_required:{field}")

    for field, allowed_values in allowed_string_values.items():
        value = submission.get(field)
        if isinstance(value, str) and value in allowed_values:
            checks_passed += 1
        else:
            failed_checks.append(f"allowed_value:{field}")

    checks_total = (
        len(required_fields)
        + len(non_empty_array_fields)
        + len(allowed_string_values)
    )
    score = checks_passed / checks_total

    deterministic_json_write(
        {
            "ok": True,
            "details": {
                "comparison_kind": "structured_validation",
                "selected_metric": "validation_score",
                "selected_metric_value": float(round(score, 12)),
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "failed_checks": failed_checks,
            },
            "matched_rows": checks_passed,
            "score": float(round(score, 12)),
            "total_rows": checks_total,
        }
    )


def read_binary_document(path: Path, label: str, runtime_error: bool) -> bytes:
    if not path.exists():
        message = f"Missing required file: {path}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)

    try:
        return path.read_bytes()
    except Exception as error:
        message = f"{label} could not be read as bytes: {error}"
        if runtime_error:
            fail_runtime(message)
        reject_submission(message)

    raise AssertionError("unreachable")


def compare_byte_exact_match(evaluation_path: Path, submission_path: Path) -> None:
    truth = read_binary_document(evaluation_path, "Evaluation bundle", True)
    submission = read_binary_document(submission_path, "Submission", False)
    matched = truth == submission
    score = 1.0 if matched else 0.0

    deterministic_json_write(
        {
            "ok": True,
            "details": {
                "comparison_kind": "byte_exact_match",
                "selected_metric": "exact_match",
                "selected_metric_value": score,
            },
            "matched_rows": 1 if matched else 0,
            "score": score,
            "total_rows": 1,
        }
    )


def main() -> None:
    runtime_config = load_runtime_config()
    evaluation_path = runtime_config["evaluation_path"]
    submission_path = runtime_config["submission_path"]

    if runtime_config["comparison_kind"] == "csv_exact_match":
        compare_csv_exact_match(evaluation_path, submission_path)
        return

    if runtime_config["comparison_kind"] == "json_exact_match":
        compare_json_exact_match(evaluation_path, submission_path)
        return

    if runtime_config["comparison_kind"] == "structured_validation":
        compare_structured_record_validation(evaluation_path, submission_path)
        return

    compare_byte_exact_match(evaluation_path, submission_path)


if __name__ == "__main__":
    main()
