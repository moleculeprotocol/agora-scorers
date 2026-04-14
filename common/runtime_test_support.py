import hashlib
import json
from pathlib import Path


def build_official_runtime_profile(
    profile_id: str = "official_compiled_runtime",
) -> dict:
    return {
        "kind": "official",
        "profile_id": profile_id,
        "image": "ghcr.io/moleculeprotocol/agora-scorer-compiled@sha256:1111111111111111111111111111111111111111111111111111111111111111",
        "limits": {
            "memory": "2g",
            "cpus": "2",
            "pids": 64,
            "timeoutMs": 600_000,
        },
        "supported_step_kinds": [
            "table_metric",
            "ranking_metric",
            "exact_match",
            "rubric_validation",
            "harness_execution",
            "compiled_program",
            "aggregate",
        ],
        "supported_program_abi_versions": ["python-v1"],
    }


def build_external_runtime_profile(
    image: str = "ghcr.io/acme/external-scorer@sha256:2222222222222222222222222222222222222222222222222222222222222222",
) -> dict:
    return {
        "kind": "external",
        "profile_id": "external",
        "image": image,
        "limits": {
            "memory": "256m",
            "cpus": "0.5",
            "pids": 32,
            "timeoutMs": 30_000,
        },
        "supported_step_kinds": ["compiled_program"],
        "supported_program_abi_versions": ["python-v1"],
    }


def write_runtime_payload(path: Path, payload: str | bytes) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        return payload

    encoded = payload.encode("utf-8")
    path.write_bytes(encoded)
    return encoded


def stage_runtime_artifact(
    input_dir: Path,
    *,
    lane: str,
    role: str,
    file_name: str,
    payload: str | bytes,
    validator: dict,
    required: bool = True,
    mime_type: str | None = None,
) -> dict:
    artifact_path = input_dir / lane / role / file_name
    content_bytes = write_runtime_payload(artifact_path, payload)
    return {
        "lane": lane,
        "role": role,
        "required": required,
        "present": True,
        "validator": validator,
        "relative_path": f"{lane}/{role}/{file_name}",
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
    }


def stage_scoring_asset(
    input_dir: Path,
    *,
    role: str,
    kind: str,
    artifact_id: str,
    file_name: str,
    payload: str | bytes,
    abi_version: str | None = None,
    entrypoint: str | None = None,
) -> dict:
    asset_path = input_dir / "scoring_assets" / role / file_name
    content_bytes = write_runtime_payload(asset_path, payload)
    staged_asset = {
        "role": role,
        "kind": kind,
        "artifact_id": artifact_id,
        "relative_path": f"scoring_assets/{role}/{file_name}",
        "file_name": file_name,
        "size_bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
    }
    if abi_version is not None:
        staged_asset["abi_version"] = abi_version
    if entrypoint is not None:
        staged_asset["entrypoint"] = entrypoint
    return staged_asset


def absent_runtime_artifact(
    *,
    lane: str,
    role: str,
    validator: dict,
    required: bool,
) -> dict:
    return {
        "lane": lane,
        "role": role,
        "required": required,
        "present": False,
        "validator": validator,
    }


def write_runtime_manifest(
    input_dir: Path,
    *,
    runtime_profile: dict,
    artifact_contract: dict,
    artifacts: list[dict],
    scoring_assets: list[dict] | None = None,
    objective: str = "maximize",
    final_score_key: str = "final_score",
    scorer_result_schema: dict | None = None,
    evaluation_bindings: list[dict] | None = None,
    policies: dict | None = None,
) -> dict:
    runtime_manifest = {
        "kind": "runtime_manifest",
        "runtime_profile": runtime_profile,
        "artifact_contract": artifact_contract,
        "evaluation_bindings": evaluation_bindings or [],
        "artifacts": artifacts,
        "scoring_assets": scoring_assets or [],
        "objective": objective,
        "final_score_key": final_score_key,
        "policies": policies
        or {
            "coverage_policy": "reject",
            "duplicate_id_policy": "reject",
            "invalid_value_policy": "reject",
        },
    }
    if scorer_result_schema is not None:
        runtime_manifest["scorer_result_schema"] = scorer_result_schema
    manifest_path = input_dir / "runtime-manifest.json"
    manifest_path.write_text(json.dumps(runtime_manifest), encoding="utf-8")
    return runtime_manifest


def read_score_output(output_dir: Path) -> dict:
    return json.loads((output_dir / "score.json").read_text(encoding="utf-8"))
