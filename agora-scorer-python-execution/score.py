"""
Agora Code Executor

Runs one or more solver-submitted Python scripts against hidden deterministic
harness bundles and scores by mean pass rate.
"""

import json
import os
import subprocess
import sys
import tempfile
import zipfile
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
DEFAULT_TIMEOUT_MS = 5_000
MAX_TIMEOUT_MS = 30_000
MAX_TESTS = 128


def deterministic_json_write(payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def fail_runtime(message: str) -> None:
    deterministic_json_write({"ok": False, "score": 0.0, "error": message, "details": {}})
    raise SystemExit(1)


def normalize_file_extension(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip().lower()
    if not trimmed:
        return None
    return trimmed if trimmed.startswith(".") else f".{trimmed}"


def require_file_slot(
    slot: dict,
    slot_label: str,
    *,
    expected_extension: str,
    expected_validator_kind: str,
) -> None:
    validator = slot.get("validator")
    if not isinstance(validator, dict):
        fail_runtime(f"Runtime manifest slot {slot_label} is missing validator.")
    if validator.get("kind") != expected_validator_kind:
        fail_runtime(
            f"Runtime manifest slot {slot_label} must use validator.kind={expected_validator_kind}."
        )

    file_contract = slot.get("file")
    if not isinstance(file_contract, dict):
        fail_runtime(f"Runtime manifest slot {slot_label} is missing file metadata.")

    extension = normalize_file_extension(file_contract.get("extension"))
    if extension != expected_extension:
        fail_runtime(
            f"Runtime manifest slot {slot_label} must declare extension {expected_extension}."
        )


def load_runtime_config() -> dict:
    runtime_manifest = load_runtime_manifest(
        input_dir=INPUT_DIR,
        fail_runtime=fail_runtime,
    )
    metric = runtime_manifest["metric"]
    if metric != "pass_rate":
        fail_runtime("Unsupported metric. official_python_execution requires pass_rate.")

    template = require_relation_plan_template(
        runtime_manifest,
        kind="execute_against",
        fail_runtime=fail_runtime,
    )
    relation_sets = resolve_relation_artifact_sets(
        runtime_manifest,
        template=template,
        fail_runtime=fail_runtime,
    )
    for relation_set in relation_sets:
        evaluation_artifact = relation_set["evaluation"][0]
        submission_artifact = relation_set["submission"][0]
        require_file_slot(
            evaluation_artifact["slot"],
            f"evaluation.{evaluation_artifact['role']}",
            expected_extension=".zip",
            expected_validator_kind="archive_layout",
        )
        require_file_slot(
            submission_artifact["slot"],
            f"submission.{submission_artifact['role']}",
            expected_extension=".py",
            expected_validator_kind="none",
        )

    return {
        "aggregation": template["aggregation"],
        "relation_sets": relation_sets,
    }


def read_json_file(path: Path, label: str) -> dict:
    if not path.exists():
        fail_runtime(f"Missing required {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail_runtime(f"{label} is not valid JSON: {error.msg}")
    if not isinstance(payload, dict):
        fail_runtime(f"{label} must be a JSON object.")
    return payload


def validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail_runtime(f"Harness field {field_name} must be a non-empty string.")
    candidate = value.strip()
    normalized = Path(candidate)
    if normalized.is_absolute():
        fail_runtime(f"Harness field {field_name} must be a relative path.")
    if ".." in normalized.parts:
        fail_runtime(f"Harness field {field_name} must not escape the harness root.")
    return candidate


def load_harness_manifest(harness_root: Path) -> dict:
    manifest = read_json_file(harness_root / "agora-harness.json", "agora-harness.json")
    if manifest.get("version") != "v1":
        fail_runtime("agora-harness.json must declare version=v1.")
    if manifest.get("language") != "python":
        fail_runtime("agora-harness.json must declare language=python.")

    timeout_ms = manifest.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    if (
        not isinstance(timeout_ms, int)
        or timeout_ms <= 0
        or timeout_ms > MAX_TIMEOUT_MS
    ):
        fail_runtime(
            f"agora-harness.json timeout_ms must be an integer between 1 and {MAX_TIMEOUT_MS}."
        )

    strip_trailing_whitespace = manifest.get("strip_trailing_whitespace", True)
    if not isinstance(strip_trailing_whitespace, bool):
        fail_runtime("agora-harness.json strip_trailing_whitespace must be a boolean.")

    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests:
        fail_runtime("agora-harness.json must declare a non-empty tests array.")
    if len(tests) > MAX_TESTS:
        fail_runtime(f"agora-harness.json cannot declare more than {MAX_TESTS} tests.")

    normalized_tests = []
    for index, test_case in enumerate(tests):
        if not isinstance(test_case, dict):
            fail_runtime(f"agora-harness.json tests[{index}] must be an object.")
        name = test_case.get("name")
        if not isinstance(name, str) or not name.strip():
            fail_runtime(f"agora-harness.json tests[{index}].name must be a non-empty string.")
        stdin_path = validate_relative_path(
            test_case.get("stdin_path"),
            f"tests[{index}].stdin_path",
        )
        expected_stdout_path = validate_relative_path(
            test_case.get("expected_stdout_path"),
            f"tests[{index}].expected_stdout_path",
        )
        normalized_tests.append(
            {
                "name": name.strip(),
                "stdin_path": stdin_path,
                "expected_stdout_path": expected_stdout_path,
            }
        )

    return {
        "timeout_ms": timeout_ms,
        "strip_trailing_whitespace": strip_trailing_whitespace,
        "tests": normalized_tests,
    }


def extract_harness_bundle(bundle_path: Path, destination_root: Path) -> Path:
    if not bundle_path.exists():
        fail_runtime(f"Missing required evaluation bundle: {bundle_path}")
    try:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    fail_runtime(
                        "Evaluation bundle contains an invalid path. Next step: rebuild the harness zip with only relative file paths."
                    )
                if member.is_dir():
                    (destination_root / member_path).mkdir(parents=True, exist_ok=True)
                    continue

                target_path = destination_root / member_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, target_path.open(
                    "wb"
                ) as destination:
                    destination.write(source.read())
    except zipfile.BadZipFile:
        fail_runtime("Evaluation bundle is not a valid zip archive.")
    return destination_root


def normalize_output(value: str, strip_trailing_whitespace: bool) -> str:
    return value.strip() if strip_trailing_whitespace else value


def run_python_test_case(test_case: dict) -> dict:
    submission_path = test_case["submission_path"]
    harness_root = test_case["harness_root"]
    stdin_path = test_case["stdin_path"]
    expected_stdout_path = test_case["expected_stdout_path"]
    timeout_ms = test_case["timeout_ms"]
    strip_trailing_whitespace = test_case["strip_trailing_whitespace"]
    name = test_case["name"]

    if not stdin_path.exists():
        fail_runtime(f"Harness test input is missing: {stdin_path}")
    if not expected_stdout_path.exists():
        fail_runtime(f"Harness expected output is missing: {expected_stdout_path}")

    expected_stdout = normalize_output(
        expected_stdout_path.read_text(encoding="utf-8"),
        strip_trailing_whitespace,
    )

    with stdin_path.open("r", encoding="utf-8") as stdin_handle:
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(submission_path)],
                cwd=str(harness_root),
                stdin=stdin_handle,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000,
                env={
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "PYTHONUNBUFFERED": "1",
                },
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "name": name,
                "passed": False,
                "reason": "timeout",
            }

    observed_stdout = normalize_output(
        result.stdout,
        strip_trailing_whitespace,
    )
    passed = result.returncode == 0 and observed_stdout == expected_stdout

    failure_details = {}
    if not passed:
        failure_details = {
            "name": name,
            "passed": False,
            "reason": "mismatch" if result.returncode == 0 else "runtime_error",
            "return_code": result.returncode,
            "stderr": result.stderr.strip()[:500],
        }

    return {
        "name": name,
        "passed": passed,
        **failure_details,
    }


def score_relation(relation_artifact_set: dict) -> dict:
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

    with tempfile.TemporaryDirectory(prefix="agora-code-executor-") as temp_dir:
        harness_root = extract_harness_bundle(
            evaluation_path,
            Path(temp_dir) / "harness",
        )
        manifest = load_harness_manifest(harness_root)

        results = []
        passed_count = 0
        for test_case in manifest["tests"]:
            test_result = run_python_test_case(
                {
                    "submission_path": submission_path,
                    "harness_root": harness_root,
                    "stdin_path": harness_root / test_case["stdin_path"],
                    "expected_stdout_path": harness_root
                    / test_case["expected_stdout_path"],
                    "timeout_ms": manifest["timeout_ms"],
                    "strip_trailing_whitespace": manifest[
                        "strip_trailing_whitespace"
                    ],
                    "name": test_case["name"],
                }
            )
            results.append(test_result)
            if test_result["passed"]:
                passed_count += 1

    total_tests = len(results)
    score = passed_count / total_tests if total_tests > 0 else 0.0
    return {
        "score": score,
        "details": {
            "comparison_kind": "execution_judge",
            "selected_metric": "pass_rate",
            "selected_metric_value": score,
            "tests_passed": passed_count,
            "tests_total": total_tests,
            "results": results,
        },
    }


def main() -> None:
    runtime = load_runtime_config()
    relation_results = []
    relation_scores = []

    for relation_artifact_set in runtime["relation_sets"]:
        relation_result = score_relation(relation_artifact_set)
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
        aggregation=runtime["aggregation"],
        fail_runtime=fail_runtime,
    )
    deterministic_json_write(
        {
            "ok": True,
            "score": float(round(aggregated_score, 12)),
            "details": {
                "aggregation": runtime["aggregation"],
                "relation_count": len(relation_results),
                "selected_metric": "pass_rate",
                "selected_metric_value": float(round(aggregated_score, 12)),
                "relation_scores": relation_results,
            },
        }
    )


if __name__ == "__main__":
    main()
