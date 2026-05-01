import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "agora-scorer-compiled" / "entrypoint.py"
COMMON_DIR = ROOT_DIR / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_test_support import (
    build_official_runtime_profile,
    read_score_output,
    stage_runtime_artifact,
    stage_scoring_asset,
    write_runtime_manifest,
)


def load_scorer_module():
    spec = importlib.util.spec_from_file_location("agora_scorer_compiled", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load compiled scorer module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_artifact_contract() -> dict:
    slot = {
        "required": True,
        "description": "Deterministic JSON payload",
        "file": {
            "extension": ".json",
            "mime_type": "application/json",
            "max_bytes": 4096,
        },
        "validator": {
            "kind": "json_document",
        },
    }
    return {
        "evaluation": [
            {
                **slot,
                "role": "reference",
            }
        ],
        "submission": [
            {
                **slot,
                "role": "candidate",
            }
        ],
        "relations": [
            {
                "kind": "exact_match",
                "evaluation_role": "reference",
                "submission_role": "candidate",
            }
        ],
    }


def build_sdk_program_source(mode: str) -> str:
    return f"""
from agora_runtime import (
    load_json_file,
    load_runtime_context,
    reject_submission,
    resolve_evaluation_artifact,
    resolve_scoring_asset,
    resolve_submission_artifact,
    write_score,
)


def main():
    runtime_context = load_runtime_context()
    reference = load_json_file(
        resolve_evaluation_artifact(runtime_context, "reference"),
        label="Reference payload",
    )
    candidate = load_json_file(
        resolve_submission_artifact(runtime_context, "candidate"),
        label="Candidate payload",
    )
    config = load_json_file(
        resolve_scoring_asset(runtime_context, "compiled_config", kind="config"),
        label="Compiled config",
    )

    if candidate.get("valid", True) is False:
        reject_submission(
            "Candidate payload is marked invalid.",
            details={{"reason": "explicit_invalid_flag"}},
        )

    final_score = 1.0 if reference.get("answer") == candidate.get("answer") else 0.25
    write_score(
        score=final_score,
        details={{
            "final_score": final_score,
            "mode": config.get("mode"),
            "objective": runtime_context["objective"],
            "final_score_key": runtime_context["final_score_key"],
        }},
    )


if __name__ == "__main__":
    main()
""".strip()


def build_runtime_sdk_fixture_source() -> str:
    return r"""
import json
import os
from pathlib import Path

from runtime_manifest import (
    load_runtime_manifest,
    resolve_artifact_by_role,
    resolve_scoring_asset_by_role,
)


def _output_path():
    return Path(os.environ["AGORA_RUNTIME_OUTPUT_ROOT"]) / "score.json"


def _write_payload(payload):
    output_path = _output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def fail_runtime(message, *, details=None):
    _write_payload({"ok": False, "score": 0.0, "error": message, "details": details or {}})
    raise SystemExit(1)


def reject_submission(message, *, details=None):
    _write_payload({"ok": False, "score": 0.0, "error": message, "details": details or {}})
    raise SystemExit(0)


def write_score(*, score, details=None):
    _write_payload({"ok": True, "score": score, "details": details or {}})


def load_runtime_context():
    return load_runtime_manifest(
        input_dir=Path(os.environ["AGORA_RUNTIME_INPUT_ROOT"]),
        fail_runtime=fail_runtime,
    )


def resolve_evaluation_artifact(runtime_context, role):
    return resolve_artifact_by_role(
        runtime_context,
        lane="evaluation",
        role=role,
        fail_runtime=fail_runtime,
    )["path"]


def resolve_submission_artifact(runtime_context, role):
    return resolve_artifact_by_role(
        runtime_context,
        lane="submission",
        role=role,
        fail_runtime=fail_runtime,
    )["path"]


def resolve_scoring_asset(runtime_context, role, *, kind=None):
    return resolve_scoring_asset_by_role(
        runtime_context,
        role=role,
        kind=kind,
        fail_runtime=fail_runtime,
    )["path"]


def load_json_file(path, *, label="JSON file"):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail_runtime(f"{label} is not valid JSON: {exc}")
""".strip()


def run_case(
    *,
    runtime_profile: dict,
    reference_payload: str,
    candidate_payload: str,
    include_program_asset: bool = True,
    include_runtime_sdk_asset: bool = True,
    config_payload: str = '{"mode": "weighted_composite"}',
):
    module = load_scorer_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-scorer-compiled-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    artifact_contract = build_artifact_contract()
    reference_artifact = stage_runtime_artifact(
        input_dir,
        lane="evaluation",
        role="reference",
        file_name="reference.json",
        payload=reference_payload,
        validator=artifact_contract["evaluation"][0]["validator"],
        mime_type="application/json",
    )
    candidate_artifact = stage_runtime_artifact(
        input_dir,
        lane="submission",
        role="candidate",
        file_name="candidate.json",
        payload=candidate_payload,
        validator=artifact_contract["submission"][0]["validator"],
        mime_type="application/json",
    )
    scoring_assets = [
        stage_scoring_asset(
            input_dir,
            role="compiled_config",
            kind="config",
            artifact_id="score-config.json",
            file_name="score-config.json",
            payload=config_payload,
        )
    ]
    if include_runtime_sdk_asset:
        scoring_assets.append(
            stage_scoring_asset(
                input_dir,
                role="python_v1_runtime_sdk",
                kind="document",
                artifact_id="agora_runtime.py",
                file_name="agora_runtime.py",
                payload=build_runtime_sdk_fixture_source(),
            )
        )
    if include_program_asset:
        scoring_assets.insert(
            0,
            stage_scoring_asset(
                input_dir,
                role="compiled_program",
                kind="program",
                artifact_id="score.py",
                file_name="score.py",
                payload=build_sdk_program_source("weighted_composite"),
                abi_version="python-v1",
                entrypoint="score.py",
            ),
        )

    write_runtime_manifest(
        input_dir,
        runtime_profile=runtime_profile,
        artifact_contract=artifact_contract,
        artifacts=[reference_artifact, candidate_artifact],
        scoring_assets=scoring_assets,
        objective="maximize",
        final_score_key="final_score",
        scorer_result_schema={
            "dimensions": ["final_score"],
            "summary_fields": [
                {"key": "mode", "value_type": "string"},
                {"key": "objective", "value_type": "string"},
                {"key": "final_score_key", "value_type": "string"},
            ],
            "allow_additional_details": True,
        },
        evaluation_bindings=[{"role": "reference", "artifact_id": "artifact-ref"}],
    )

    module.INPUT_DIR = input_dir
    module.OUTPUT_DIR = output_dir
    module.OUTPUT_PATH = output_dir / "score.json"

    exit_code = 0
    try:
        module.main()
    except SystemExit as exc:
        exit_code = int(exc.code or 0)

    payload = None
    if (output_dir / "score.json").exists():
        payload = read_score_output(output_dir)
    shutil.rmtree(workspace)
    return exit_code, payload


def main() -> None:
    exit_code, payload = run_case(
        runtime_profile=build_official_runtime_profile(),
        reference_payload=json.dumps({"answer": "pep-1"}),
        candidate_payload=json.dumps({"answer": "pep-1"}),
    )
    assert exit_code == 0, payload
    assert payload is not None
    assert payload["ok"] is True, payload
    assert payload["score"] == 1.0, payload
    assert payload["details"]["mode"] == "weighted_composite", payload
    assert payload["details"]["final_score_key"] == "final_score", payload

    exit_code, payload = run_case(
        runtime_profile=build_official_runtime_profile(),
        reference_payload=json.dumps({"answer": "pep-1"}),
        candidate_payload=json.dumps({"answer": "pep-2", "valid": False}),
    )
    assert exit_code == 0, payload
    assert payload is not None
    assert payload["ok"] is False, payload
    assert payload["details"]["reason"] == "explicit_invalid_flag", payload

    exit_code, payload = run_case(
        runtime_profile=build_official_runtime_profile(),
        reference_payload=json.dumps({"answer": "pep-1"}),
        candidate_payload=json.dumps({"answer": "pep-1"}),
        include_program_asset=False,
    )
    assert exit_code == 1, exit_code
    assert payload is not None
    assert "exactly one program scoring asset" in payload["error"], payload

    exit_code, payload = run_case(
        runtime_profile=build_official_runtime_profile(),
        reference_payload=json.dumps({"answer": "pep-1"}),
        candidate_payload=json.dumps({"answer": "pep-1"}),
        include_runtime_sdk_asset=False,
    )
    assert exit_code == 1, exit_code
    assert payload is not None
    assert "python_v1_runtime_sdk" in payload["error"], payload

    unsupported_runtime_profile = {
        **build_official_runtime_profile(),
        "kind": "partner",
    }
    exit_code, payload = run_case(
        runtime_profile=unsupported_runtime_profile,
        reference_payload=json.dumps({"answer": "pep-1"}),
        candidate_payload=json.dumps({"answer": "pep-1"}),
    )
    assert exit_code == 1, exit_code
    assert payload is not None
    assert "Unsupported kind in runtime manifest" in payload["error"], payload

    print("compiled scorer tests passed")


if __name__ == "__main__":
    main()
