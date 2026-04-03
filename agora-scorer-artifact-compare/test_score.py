import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "agora-scorer-artifact-compare" / "score.py"
COMMON_DIR = ROOT_DIR / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_test_support import stage_runtime_artifact, write_runtime_manifest


def load_scorer_module():
    spec = importlib.util.spec_from_file_location("agora_repro_scorer", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load reproducibility scorer module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_exact_match_contract(
    *,
    validator: dict,
    extension: str,
    mime_type: str | None,
) -> dict:
    relations = [
        {
            "kind": "exact_match",
            "evaluation_role": "reference",
            "submission_role": "answer",
        }
    ]
    slot_file = {
        "extension": extension,
        "max_bytes": 4096,
    }
    if mime_type is not None:
        slot_file["mime_type"] = mime_type

    return {
        "evaluation": [
            {
                "role": "reference",
                "required": True,
                "description": "Hidden reference artifact",
                "file": dict(slot_file),
                "validator": validator,
            }
        ],
        "submission": [
            {
                "role": "answer",
                "required": True,
                "description": "Solver answer artifact",
                "file": dict(slot_file),
                "validator": validator,
            }
        ],
        "relations": relations,
    }


def build_structured_validation_contract() -> dict:
    relations = [
        {
            "kind": "structured_validation",
            "evaluation_role": "rubric",
            "submission_role": "record",
        }
    ]
    json_slot_file = {
        "extension": ".json",
        "mime_type": "application/json",
        "max_bytes": 4096,
    }
    return {
        "evaluation": [
            {
                "role": "rubric",
                "required": True,
                "description": "Hidden structured validation rubric",
                "file": dict(json_slot_file),
                "validator": {"kind": "json_document"},
            }
        ],
        "submission": [
            {
                "role": "record",
                "required": True,
                "description": "Solver JSON record",
                "file": dict(json_slot_file),
                "validator": {"kind": "json_document"},
            }
        ],
        "relations": relations,
    }


def run_case(
    *,
    artifact_contract: dict,
    metric: str,
    comparator: str,
    evaluation_role: str,
    evaluation_file_name: str,
    evaluation_payload: str | bytes,
    submission_role: str,
    submission_file_name: str,
    submission_payload: str | bytes,
    runtime_manifest: dict | None = None,
):
    module = load_scorer_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-agora-scorer-artifact-compare-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    evaluation_slot = artifact_contract["evaluation"][0]
    submission_slot = artifact_contract["submission"][0]
    evaluation_artifact = stage_runtime_artifact(
        input_dir,
        lane="evaluation",
        role=evaluation_role,
        file_name=evaluation_file_name,
        payload=evaluation_payload,
        validator=evaluation_slot["validator"],
        mime_type=evaluation_slot["file"].get("mime_type"),
    )
    submission_artifact = stage_runtime_artifact(
        input_dir,
        lane="submission",
        role=submission_role,
        file_name=submission_file_name,
        payload=submission_payload,
        validator=submission_slot["validator"],
        mime_type=submission_slot["file"].get("mime_type"),
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


csv_contract = build_exact_match_contract(
    validator={
        "kind": "csv_columns",
        "required": ["id", "value"],
        "record_key": "id",
        "value_field": "value",
        "allow_extra": True,
    },
    extension=".csv",
    mime_type="text/csv",
)
exit_code, payload = run_case(
    artifact_contract=csv_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.csv",
    evaluation_payload="id,value\nrow-1,1\nrow-2,2\n",
    submission_role="answer",
    submission_file_name="answer.csv",
    submission_payload="id,value\nrow-1,1\nrow-2,2\n",
)
assert exit_code == 0, f"csv exact-match run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["comparison_kind"] == "csv_exact_match", payload

json_contract = build_exact_match_contract(
    validator={"kind": "json_document"},
    extension=".json",
    mime_type="application/json",
)
exit_code, payload = run_case(
    artifact_contract=json_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.json",
    evaluation_payload='{"result":{"value":42,"status":"ok"}}',
    submission_role="answer",
    submission_file_name="answer.json",
    submission_payload='{"result":{"status":"ok","value":42}}',
)
assert exit_code == 0, f"json exact-match run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["comparison_kind"] == "json_exact_match", payload

exit_code, payload = run_case(
    artifact_contract=json_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.json",
    evaluation_payload='{"result":{"value":42,"status":"ok"}}',
    submission_role="answer",
    submission_file_name="answer.json",
    submission_payload='{"result":{"status":"ok","value":43}}',
)
assert exit_code == 0, f"json mismatch run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 0.0, payload

structured_contract = build_structured_validation_contract()
exit_code, payload = run_case(
    artifact_contract=structured_contract,
    metric="validation_score",
    comparator="maximize",
    evaluation_role="rubric",
    evaluation_file_name="rubric.json",
    evaluation_payload=json.dumps(
        {
            "required_fields": [
                "incident_id",
                "severity",
                "timeline",
                "actions_taken",
            ],
            "non_empty_array_fields": ["timeline", "actions_taken"],
            "allowed_string_values": {
                "severity": ["low", "medium", "high"],
            },
        }
    ),
    submission_role="record",
    submission_file_name="record.json",
    submission_payload=json.dumps(
        {
            "incident_id": "INC-2042",
            "severity": "high",
            "timeline": [{"timestamp": "2026-03-01T10:00:00Z", "event": "alert"}],
            "actions_taken": ["isolated service"],
        }
    ),
)
assert exit_code == 0, f"structured-record validation run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["comparison_kind"] == "structured_validation", payload
assert payload["details"]["checks_passed"] == payload["details"]["checks_total"], payload

exit_code, payload = run_case(
    artifact_contract=structured_contract,
    metric="validation_score",
    comparator="maximize",
    evaluation_role="rubric",
    evaluation_file_name="rubric.json",
    evaluation_payload=json.dumps(
        {
            "required_fields": [
                "incident_id",
                "severity",
                "timeline",
                "actions_taken",
            ],
            "non_empty_array_fields": ["timeline", "actions_taken"],
            "allowed_string_values": {
                "severity": ["low", "medium", "high"],
            },
        }
    ),
    submission_role="record",
    submission_file_name="record.json",
    submission_payload=json.dumps(
        {
            "incident_id": "INC-2042",
            "severity": "critical",
            "actions_taken": [],
        }
    ),
)
assert exit_code == 0, f"structured-record invalid run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] < 0.5, payload
assert "missing_or_empty:timeline" in payload["details"]["failed_checks"], payload
assert "array_required:actions_taken" in payload["details"]["failed_checks"], payload
assert "allowed_value:severity" in payload["details"]["failed_checks"], payload

byte_contract = build_exact_match_contract(
    validator={"kind": "none"},
    extension=".pdf",
    mime_type="application/pdf",
)
exit_code, payload = run_case(
    artifact_contract=byte_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.pdf",
    evaluation_payload=b"%PDF-1.7\nmock reference document\n",
    submission_role="answer",
    submission_file_name="answer.pdf",
    submission_payload=b"%PDF-1.7\nmock reference document\n",
)
assert exit_code == 0, f"byte exact-match run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["comparison_kind"] == "byte_exact_match", payload

exit_code, payload = run_case(
    artifact_contract=byte_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.pdf",
    evaluation_payload=b"%PDF-1.7\nmock reference document\n",
    submission_role="answer",
    submission_file_name="answer.pdf",
    submission_payload=b"%PDF-1.7\nchanged solver document\n",
)
assert exit_code == 0, f"byte mismatch run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 0.0, payload

exit_code, payload = run_case(
    artifact_contract=csv_contract,
    metric="validation_score",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.csv",
    evaluation_payload="id,value\nrow-1,1\nrow-2,2\n",
    submission_role="answer",
    submission_file_name="answer.csv",
    submission_payload="id,value\nrow-1,1\nrow-2,2\n",
)
assert exit_code == 1, f"wrong exact-match metric should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "metric=exact_match" in payload["error"], payload

invalid_kind_manifest = {
    "kind": "agora_runtime",
    "metric": "exact_match",
    "comparator": "maximize",
    "artifact_contract": csv_contract,
    "evaluation_bindings": [],
    "artifacts": [],
    "policies": {
        "coverage_policy": "reject",
        "duplicate_id_policy": "reject",
        "invalid_value_policy": "reject",
    },
}
exit_code, payload = run_case(
    artifact_contract=csv_contract,
    metric="exact_match",
    comparator="maximize",
    evaluation_role="reference",
    evaluation_file_name="reference.csv",
    evaluation_payload="id,value\nrow-1,1\nrow-2,2\n",
    submission_role="answer",
    submission_file_name="answer.csv",
    submission_payload="id,value\nrow-1,1\nrow-2,2\n",
    runtime_manifest=invalid_kind_manifest,
)
assert exit_code == 1, f"invalid manifest kind should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "kind=runtime_manifest" in payload["error"], payload

print("match scorer runtime tests passed")
