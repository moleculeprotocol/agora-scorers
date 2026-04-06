import hashlib
import json
from pathlib import Path


def build_official_scorer(scorer_id: str) -> dict:
    return {
        "kind": "official",
        "id": scorer_id,
        "image": f"ghcr.io/agora/{scorer_id}@sha256:test",
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
    scorer: dict,
    metric: str,
    comparator: str,
    artifact_contract: dict,
    relation_plan: dict,
    artifacts: list[dict],
    evaluation_bindings: list[dict] | None = None,
    policies: dict | None = None,
) -> dict:
    runtime_manifest = {
        "kind": "runtime_manifest",
        "scorer": scorer,
        "metric": metric,
        "comparator": comparator,
        "artifact_contract": artifact_contract,
        "relation_plan": relation_plan,
        "evaluation_bindings": evaluation_bindings or [],
        "artifacts": artifacts,
        "policies": policies
        or {
            "coverage_policy": "reject",
            "duplicate_id_policy": "reject",
            "invalid_value_policy": "reject",
        },
    }
    manifest_path = input_dir / "runtime-manifest.json"
    manifest_path.write_text(json.dumps(runtime_manifest), encoding="utf-8")
    return runtime_manifest
