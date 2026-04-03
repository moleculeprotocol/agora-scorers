import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "agora-scorer-table-metric" / "score.py"
COMMON_DIR = ROOT_DIR / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_test_support import stage_runtime_artifact, write_runtime_manifest


def load_scorer_module():
    spec = importlib.util.spec_from_file_location("agora_regression_scorer", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load regression scorer module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_artifact_contract(
    *,
    submission_id_column: str = "id",
    submission_value_column: str = "prediction",
) -> dict:
    relations = [
        {
            "kind": "tabular_alignment",
            "evaluation_role": "reference",
            "submission_role": "predictions",
        }
    ]
    return {
        "evaluation": [
            {
                "role": "reference",
                "required": True,
                "description": "Hidden ground truth table",
                "file": {
                    "extension": ".csv",
                    "mime_type": "text/csv",
                    "max_bytes": 4096,
                },
                "validator": {
                    "kind": "csv_columns",
                    "required": ["id", "label"],
                    "record_key": "id",
                    "value_field": "label",
                    "allow_extra": True,
                },
            }
        ],
        "submission": [
            {
                "role": "predictions",
                "required": True,
                "description": "Solver predictions",
                "file": {
                    "extension": ".csv",
                    "mime_type": "text/csv",
                    "max_bytes": 4096,
                },
                "validator": {
                    "kind": "csv_columns",
                    "required": [submission_id_column, submission_value_column],
                    "record_key": submission_id_column,
                    "value_field": submission_value_column,
                    "allow_extra": True,
                },
            }
        ],
        "relations": relations,
    }


def run_case(
    submission_text: str,
    *,
    submission_id_column: str = "id",
    submission_value_column: str = "prediction",
    metric: str = "r2",
    comparator: str = "maximize",
    ground_truth_text: str | None = None,
    runtime_manifest: dict | None = None,
):
    module = load_scorer_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-agora-scorer-table-metric-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    artifact_contract = build_artifact_contract(
        submission_id_column=submission_id_column,
        submission_value_column=submission_value_column,
    )
    evaluation_slot = artifact_contract["evaluation"][0]
    submission_slot = artifact_contract["submission"][0]

    evaluation_artifact = stage_runtime_artifact(
        input_dir,
        lane="evaluation",
        role="reference",
        file_name="reference.csv",
        payload=(
            ground_truth_text
            if ground_truth_text is not None
            else "id,label\ns1,10.0\ns2,11.2\ns3,9.8\ns4,12.3\ns5,13.1\ns6,8.4\ns7,7.7\ns8,15.2\ns9,10.5\ns10,9.1\n"
        ),
        validator=evaluation_slot["validator"],
        mime_type="text/csv",
    )
    submission_artifact = stage_runtime_artifact(
        input_dir,
        lane="submission",
        role="predictions",
        file_name="predictions.csv",
        payload=submission_text,
        validator=submission_slot["validator"],
        mime_type="text/csv",
    )

    if runtime_manifest is None:
        write_runtime_manifest(
            input_dir,
            metric=metric,
            comparator=comparator,
            artifact_contract=artifact_contract,
            artifacts=[evaluation_artifact, submission_artifact],
        )
    else:
        (input_dir / "runtime-manifest.json").write_text(
            json.dumps(runtime_manifest),
            encoding="utf-8",
        )

    module.INPUT_DIR = input_dir
    module.OUTPUT_DIR = output_dir
    module.OUTPUT_PATH = output_dir / "score.json"

    exit_code = 0
    try:
        module.main()
    except SystemExit as exc:
        exit_code = int(exc.code or 0)

    payload = json.loads((output_dir / "score.json").read_text(encoding="utf-8"))
    shutil.rmtree(workspace)
    return exit_code, payload


sample_submission = """id,prediction
s1,10.0
s2,11.2
s3,9.8
s4,12.3
s5,13.1
s6,8.4
s7,7.7
s8,15.2
s9,10.5
s10,9.1
"""
ground_truth = """id,label
s1,10.0
s2,11.2
s3,9.8
s4,12.3
s5,13.1
s6,8.4
s7,7.7
s8,15.2
s9,10.5
s10,9.1
"""
custom_value_submission = sample_submission.replace("id,prediction", "id,forecast")
exit_code, payload = run_case(custom_value_submission, submission_value_column="forecast")
assert exit_code == 0, f"custom column run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["details"]["matched_rows"] == 10, payload

partial_submission = "\n".join(sample_submission.strip().splitlines()[:-1]) + "\n"
exit_code, payload = run_case(partial_submission)
assert exit_code == 0, f"partial submission should be rejected as invalid, not crash: {exit_code}"
assert payload["ok"] is False, payload
assert "exactly one prediction row" in payload["error"], payload
assert payload["details"]["missing_ids"] > 0, payload

duplicate_submission = (
    sample_submission.strip() + "\n" + sample_submission.strip().splitlines()[1] + "\n"
)
exit_code, payload = run_case(duplicate_submission)
assert exit_code == 0, f"duplicate submission should be rejected as invalid, not crash: {exit_code}"
assert payload["ok"] is False, payload
assert "duplicate prediction ids" in payload["error"], payload
assert payload["details"]["duplicate_ids"] > 0, payload

nonnumeric_submission = sample_submission.replace("s4,12.3", "s4,not-a-number")
exit_code, payload = run_case(nonnumeric_submission)
assert exit_code == 0, f"nonnumeric submission should be rejected as invalid, not crash: {exit_code}"
assert payload["ok"] is False, payload
assert "non-numeric prediction values" in payload["error"], payload
assert payload["details"]["invalid_value_ids"] > 0, payload

perfect_rmse_submission = ground_truth.replace("label", "prediction")
exit_code, payload = run_case(perfect_rmse_submission, metric="rmse", comparator="minimize")
assert exit_code == 0, f"rmse run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["selected_metric"] == "rmse", payload
assert payload["details"]["selected_metric_value"] == 0.0, payload

classification_truth = "id,label\nrow-1,a\nrow-2,b\nrow-3,a\n"
classification_submission = "id,prediction\nrow-1,a\nrow-2,b\nrow-3,b\n"
exit_code, payload = run_case(
    classification_submission,
    metric="accuracy",
    ground_truth_text=classification_truth,
)
assert exit_code == 0, f"classification run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["details"]["accuracy"] == round(2 / 3, 12), payload

invalid_kind_manifest = {
    "kind": "agora_runtime",
    "metric": "r2",
    "comparator": "maximize",
    "artifact_contract": build_artifact_contract(),
    "evaluation_bindings": [],
    "artifacts": [],
    "policies": {
        "coverage_policy": "reject",
        "duplicate_id_policy": "reject",
        "invalid_value_policy": "reject",
    },
}
exit_code, payload = run_case(
    sample_submission,
    runtime_manifest=invalid_kind_manifest,
)
assert exit_code == 1, f"invalid manifest kind should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "kind=runtime_manifest" in payload["error"], payload

missing_relation_contract = build_artifact_contract()
missing_relation_contract["relations"] = []
missing_relation_manifest = {
    "kind": "runtime_manifest",
    "metric": "r2",
    "comparator": "maximize",
    "artifact_contract": missing_relation_contract,
    "evaluation_bindings": [],
    "artifacts": [
        {
            "lane": "evaluation",
            "role": "reference",
            "required": True,
            "present": True,
            "validator": missing_relation_contract["evaluation"][0]["validator"],
            "relative_path": "evaluation/reference/reference.csv",
            "file_name": "reference.csv",
            "mime_type": "text/csv",
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        {
            "lane": "submission",
            "role": "predictions",
            "required": True,
            "present": True,
            "validator": missing_relation_contract["submission"][0]["validator"],
            "relative_path": "submission/predictions/predictions.csv",
            "file_name": "predictions.csv",
            "mime_type": "text/csv",
            "size_bytes": 1,
            "sha256": "1" * 64,
        },
    ],
    "policies": {
        "coverage_policy": "reject",
        "duplicate_id_policy": "reject",
        "invalid_value_policy": "reject",
    },
}
exit_code, payload = run_case(
    sample_submission,
    runtime_manifest=missing_relation_manifest,
)
assert exit_code == 1, f"missing relation should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "missing relation kind=tabular_alignment" in payload["error"], payload

print("tabular scorer runtime tests passed")
