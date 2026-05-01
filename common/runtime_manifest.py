import json
import re
from pathlib import Path
from typing import Any, Callable

RUNTIME_MANIFEST_FILE_NAME = "runtime-manifest.json"
RUNTIME_EVALUATION_ROOT_DIR_NAME = "evaluation"
RUNTIME_SUBMISSION_ROOT_DIR_NAME = "submission"
RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME = "scoring_assets"

_COVERAGE_POLICIES = {"reject", "ignore", "penalize"}
_DUPLICATE_ID_POLICIES = {"reject", "ignore"}
_INVALID_VALUE_POLICIES = {"reject", "ignore"}
_OBJECTIVES = {"maximize", "minimize"}
_RUNTIME_PROFILE_KINDS = {"official"}
_SCORING_ASSET_KINDS = {"program", "config", "bundle", "document"}
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _require_mapping(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        fail_runtime(f"Runtime manifest {key} must be an object.")
    return value


def _require_list(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> list[Any]:
    value = container.get(key)
    if not isinstance(value, list):
        fail_runtime(f"Runtime manifest {key} must be an array.")
    return value


def _require_bool(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        fail_runtime(f"Runtime manifest {key} must be a boolean.")
    return value


def _require_non_empty_string(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        fail_runtime(f"Runtime manifest {key} must be a non-empty string.")
    return value.strip()


def _require_positive_int(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> int:
    value = container.get(key)
    if not isinstance(value, int) or value <= 0:
        fail_runtime(f"Runtime manifest {key} must be a positive integer.")
    return value


def _require_non_negative_int(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> int:
    value = container.get(key)
    if not isinstance(value, int) or value < 0:
        fail_runtime(f"Runtime manifest {key} must be a non-negative integer.")
    return value


def _require_optional_non_empty_string(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        fail_runtime(f"Runtime manifest {key} must be a non-empty string when present.")
    return value.strip()


def _require_enum_value(
    container: dict[str, Any],
    key: str,
    *,
    allowed_values: set[str],
    fail_runtime: Callable[[str], None],
) -> str:
    value = _require_non_empty_string(
        container,
        key,
        fail_runtime=fail_runtime,
    )
    if value not in allowed_values:
        fail_runtime(
            f"Unsupported {key} in runtime manifest. Expected one of {','.join(sorted(allowed_values))}."
        )
    return value


def _normalize_relative_path(
    value: Any,
    *,
    expected_root: str | None = None,
    fail_runtime: Callable[[str], None],
) -> Path:
    if not isinstance(value, str) or not value.strip():
        fail_runtime(
            "Runtime manifest present entries must include a non-empty relative_path."
        )

    normalized = value.replace("\\", "/").strip()
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail_runtime(
            f"Runtime manifest path must stay within /input. Received: {value}"
        )

    if expected_root is not None and (
        not candidate.parts or candidate.parts[0] != expected_root
    ):
        fail_runtime(
            f"Runtime manifest path must live under /input/{expected_root}. Received: {value}"
        )

    return candidate


def _require_validator(
    container: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    validator = _require_mapping(container, key, fail_runtime=fail_runtime)
    _require_non_empty_string(validator, "kind", fail_runtime=fail_runtime)
    return validator


def _require_runtime_profile(
    runtime_manifest: dict[str, Any],
    *,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    runtime_profile = _require_mapping(
        runtime_manifest,
        "runtime_profile",
        fail_runtime=fail_runtime,
    )
    kind = _require_enum_value(
        runtime_profile,
        "kind",
        allowed_values=_RUNTIME_PROFILE_KINDS,
        fail_runtime=fail_runtime,
    )
    profile_id = _require_non_empty_string(
        runtime_profile,
        "profile_id",
        fail_runtime=fail_runtime,
    )
    image = _require_non_empty_string(
        runtime_profile,
        "image",
        fail_runtime=fail_runtime,
    )
    limits = _require_mapping(runtime_profile, "limits", fail_runtime=fail_runtime)
    supported_program_abi_versions = _require_list(
        runtime_profile,
        "supported_program_abi_versions",
        fail_runtime=fail_runtime,
    )

    for key in supported_program_abi_versions:
        if not isinstance(key, str) or not key.strip():
            fail_runtime(
                "Runtime manifest runtime_profile.supported_program_abi_versions must contain non-empty strings."
            )

    return {
        "kind": kind,
        "profile_id": profile_id,
        "image": image,
        "limits": {
            "memory": _require_non_empty_string(
                limits,
                "memory",
                fail_runtime=fail_runtime,
            ),
            "cpus": _require_non_empty_string(
                limits,
                "cpus",
                fail_runtime=fail_runtime,
            ),
            "pids": _require_positive_int(
                limits,
                "pids",
                fail_runtime=fail_runtime,
            ),
            "timeoutMs": _require_positive_int(
                limits,
                "timeoutMs",
                fail_runtime=fail_runtime,
            ),
        },
        "supported_program_abi_versions": [
            value.strip() for value in supported_program_abi_versions
        ],
    }


def _require_artifact_slot_list(
    artifact_contract: dict[str, Any],
    key: str,
    *,
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    slots = _require_list(artifact_contract, key, fail_runtime=fail_runtime)
    normalized: list[dict[str, Any]] = []
    for index, raw_slot in enumerate(slots):
        if not isinstance(raw_slot, dict):
            fail_runtime(f"Runtime manifest artifact_contract.{key}[{index}] must be an object.")

        role = _require_non_empty_string(raw_slot, "role", fail_runtime=fail_runtime)
        normalized.append(
            {
                "role": role,
                "required": _require_bool(
                    raw_slot,
                    "required",
                    fail_runtime=fail_runtime,
                ),
                "description": _require_non_empty_string(
                    raw_slot,
                    "description",
                    fail_runtime=fail_runtime,
                ),
                "file": _require_mapping(raw_slot, "file", fail_runtime=fail_runtime),
                "validator": _require_validator(
                    raw_slot,
                    "validator",
                    fail_runtime=fail_runtime,
                ),
            }
        )
    return normalized


def _require_artifact_entries(
    runtime_manifest: dict[str, Any],
    *,
    evaluation_slots: list[dict[str, Any]],
    submission_slots: list[dict[str, Any]],
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    artifacts = _require_list(runtime_manifest, "artifacts", fail_runtime=fail_runtime)
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for index, raw_artifact in enumerate(artifacts):
        if not isinstance(raw_artifact, dict):
            fail_runtime(f"Runtime manifest artifacts[{index}] must be an object.")

        lane = _require_enum_value(
            raw_artifact,
            "lane",
            allowed_values={"evaluation", "submission"},
            fail_runtime=fail_runtime,
        )
        role = _require_non_empty_string(raw_artifact, "role", fail_runtime=fail_runtime)
        key = (lane, role)
        if key in seen_keys:
            fail_runtime(
                f"Runtime manifest must contain exactly one {lane} artifact entry for role {role}."
            )
        seen_keys.add(key)

        present = _require_bool(raw_artifact, "present", fail_runtime=fail_runtime)
        required = _require_bool(raw_artifact, "required", fail_runtime=fail_runtime)
        validator = _require_validator(raw_artifact, "validator", fail_runtime=fail_runtime)

        normalized_artifact: dict[str, Any] = {
            "lane": lane,
            "role": role,
            "present": present,
            "required": required,
            "validator": validator,
        }

        if present:
            relative_path = _normalize_relative_path(
                raw_artifact.get("relative_path"),
                expected_root=lane,
                fail_runtime=fail_runtime,
            )
            file_name = _require_non_empty_string(
                raw_artifact,
                "file_name",
                fail_runtime=fail_runtime,
            )
            size_bytes = _require_non_negative_int(
                raw_artifact,
                "size_bytes",
                fail_runtime=fail_runtime,
            )
            sha256 = _require_non_empty_string(
                raw_artifact,
                "sha256",
                fail_runtime=fail_runtime,
            )
            if not _SHA256_PATTERN.fullmatch(sha256):
                fail_runtime(
                    f"Runtime manifest artifacts[{index}].sha256 must be a 64-character lowercase hex string."
                )

            normalized_artifact.update(
                {
                    "relative_path": relative_path.as_posix(),
                    "file_name": file_name,
                    "mime_type": _require_optional_non_empty_string(
                        raw_artifact,
                        "mime_type",
                        fail_runtime=fail_runtime,
                    ),
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                }
            )

        normalized.append(normalized_artifact)

    for lane, slots in (
        ("evaluation", evaluation_slots),
        ("submission", submission_slots),
    ):
        for slot in slots:
            if (lane, slot["role"]) not in seen_keys:
                fail_runtime(f"Runtime manifest is missing {lane} role {slot['role']}.")

    return normalized


def _require_scoring_assets(
    runtime_manifest: dict[str, Any],
    *,
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    scoring_assets = _require_list(
        runtime_manifest,
        "scoring_assets",
        fail_runtime=fail_runtime,
    )
    normalized: list[dict[str, Any]] = []
    seen_artifact_ids: set[str] = set()

    for index, raw_asset in enumerate(scoring_assets):
        if not isinstance(raw_asset, dict):
            fail_runtime(f"Runtime manifest scoring_assets[{index}] must be an object.")

        role = _require_non_empty_string(raw_asset, "role", fail_runtime=fail_runtime)
        kind = _require_enum_value(
            raw_asset,
            "kind",
            allowed_values=_SCORING_ASSET_KINDS,
            fail_runtime=fail_runtime,
        )
        artifact_id = _require_non_empty_string(
            raw_asset,
            "artifact_id",
            fail_runtime=fail_runtime,
        )
        if artifact_id in seen_artifact_ids:
            fail_runtime(
                f"Runtime manifest scoring_assets artifact_id {artifact_id} is duplicated."
            )
        seen_artifact_ids.add(artifact_id)

        relative_path = _normalize_relative_path(
            raw_asset.get("relative_path"),
            expected_root=RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME,
            fail_runtime=fail_runtime,
        )
        file_name = _require_non_empty_string(
            raw_asset,
            "file_name",
            fail_runtime=fail_runtime,
        )
        size_bytes = _require_non_negative_int(
            raw_asset,
            "size_bytes",
            fail_runtime=fail_runtime,
        )
        sha256 = _require_non_empty_string(
            raw_asset,
            "sha256",
            fail_runtime=fail_runtime,
        )
        if not _SHA256_PATTERN.fullmatch(sha256):
            fail_runtime(
                f"Runtime manifest scoring_assets[{index}].sha256 must be a 64-character lowercase hex string."
            )

        normalized_asset = {
            "role": role,
            "kind": kind,
            "artifact_id": artifact_id,
            "relative_path": relative_path.as_posix(),
            "file_name": file_name,
            "size_bytes": size_bytes,
            "sha256": sha256,
        }

        abi_version = _require_optional_non_empty_string(
            raw_asset,
            "abi_version",
            fail_runtime=fail_runtime,
        )
        entrypoint = _require_optional_non_empty_string(
            raw_asset,
            "entrypoint",
            fail_runtime=fail_runtime,
        )

        if kind == "program":
            if not abi_version:
                fail_runtime(
                    f"Runtime manifest scoring_assets[{index}] kind=program must declare abi_version."
                )
            if not entrypoint:
                fail_runtime(
                    f"Runtime manifest scoring_assets[{index}] kind=program must declare entrypoint."
                )

        if abi_version is not None:
            normalized_asset["abi_version"] = abi_version
        if entrypoint is not None:
            normalized_asset["entrypoint"] = entrypoint

        normalized.append(normalized_asset)

    return normalized


def load_runtime_manifest(
    *,
    input_dir: Path,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    runtime_manifest_path = input_dir / RUNTIME_MANIFEST_FILE_NAME
    if not runtime_manifest_path.exists():
        fail_runtime(f"Missing required file: {runtime_manifest_path}")

    try:
        runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail_runtime(
            f"Invalid runtime manifest JSON at {runtime_manifest_path}: {error.msg}"
        )

    if runtime_manifest.get("kind") != "runtime_manifest":
        fail_runtime(
            "Unsupported runtime manifest kind. Expected kind=runtime_manifest."
        )

    runtime_profile = _require_runtime_profile(
        runtime_manifest,
        fail_runtime=fail_runtime,
    )
    artifact_contract = _require_mapping(
        runtime_manifest,
        "artifact_contract",
        fail_runtime=fail_runtime,
    )
    evaluation_slots = _require_artifact_slot_list(
        artifact_contract,
        "evaluation",
        fail_runtime=fail_runtime,
    )
    submission_slots = _require_artifact_slot_list(
        artifact_contract,
        "submission",
        fail_runtime=fail_runtime,
    )
    relations = artifact_contract.get("relations", [])
    if not isinstance(relations, list):
        fail_runtime("Runtime manifest artifact_contract.relations must be an array.")

    artifacts = _require_artifact_entries(
        runtime_manifest,
        evaluation_slots=evaluation_slots,
        submission_slots=submission_slots,
        fail_runtime=fail_runtime,
    )
    scoring_assets = _require_scoring_assets(
        runtime_manifest,
        fail_runtime=fail_runtime,
    )

    evaluation_bindings = runtime_manifest.get("evaluation_bindings", [])
    if not isinstance(evaluation_bindings, list):
        fail_runtime("Runtime manifest evaluation_bindings must be an array.")

    scorer_result_schema = runtime_manifest.get("scorer_result_schema")
    if scorer_result_schema is not None and not isinstance(scorer_result_schema, dict):
        fail_runtime("Runtime manifest scorer_result_schema must be an object.")

    policies = _require_mapping(
        runtime_manifest,
        "policies",
        fail_runtime=fail_runtime,
    )
    coverage_policy = _require_enum_value(
        policies,
        "coverage_policy",
        allowed_values=_COVERAGE_POLICIES,
        fail_runtime=fail_runtime,
    )
    duplicate_id_policy = _require_enum_value(
        policies,
        "duplicate_id_policy",
        allowed_values=_DUPLICATE_ID_POLICIES,
        fail_runtime=fail_runtime,
    )
    invalid_value_policy = _require_enum_value(
        policies,
        "invalid_value_policy",
        allowed_values=_INVALID_VALUE_POLICIES,
        fail_runtime=fail_runtime,
    )

    return {
        "runtime_profile": runtime_profile,
        "artifact_contract": artifact_contract,
        "evaluation_slots": evaluation_slots,
        "submission_slots": submission_slots,
        "artifacts": artifacts,
        "relations": relations,
        "scoring_assets": scoring_assets,
        "evaluation_bindings": evaluation_bindings,
        "objective": _require_enum_value(
            runtime_manifest,
            "objective",
            allowed_values=_OBJECTIVES,
            fail_runtime=fail_runtime,
        ),
        "final_score_key": _require_non_empty_string(
            runtime_manifest,
            "final_score_key",
            fail_runtime=fail_runtime,
        ),
        "scorer_result_schema": scorer_result_schema,
        "policies": {
            "coverage_policy": coverage_policy,
            "duplicate_id_policy": duplicate_id_policy,
            "invalid_value_policy": invalid_value_policy,
        },
        "input_dir": input_dir,
        "runtime_manifest_path": runtime_manifest_path,
        "evaluation_root": input_dir / RUNTIME_EVALUATION_ROOT_DIR_NAME,
        "submission_root": input_dir / RUNTIME_SUBMISSION_ROOT_DIR_NAME,
        "scoring_assets_root": input_dir / RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME,
    }


def _find_slot(
    runtime_manifest: dict[str, Any],
    *,
    lane: str,
    role: str,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    slot_key = f"{lane}_slots"
    slots = runtime_manifest.get(slot_key)
    if not isinstance(slots, list):
        fail_runtime(f"Runtime manifest is missing {slot_key}.")

    slot = next(
        (
            candidate
            for candidate in slots
            if isinstance(candidate, dict) and candidate.get("role") == role
        ),
        None,
    )
    if slot is None:
        fail_runtime(f"Runtime manifest is missing {lane} slot role {role}.")

    return slot


def resolve_artifact_by_role(
    runtime_manifest: dict[str, Any],
    *,
    lane: str,
    role: str,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    slot = _find_slot(
        runtime_manifest,
        lane=lane,
        role=role,
        fail_runtime=fail_runtime,
    )

    artifacts = runtime_manifest.get("artifacts", [])
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("lane") == lane
        and artifact.get("role") == role
    ]
    if len(matches) != 1:
        fail_runtime(
            f"Runtime manifest must contain exactly one {lane} artifact entry for role {role}."
        )

    artifact = matches[0]
    if artifact.get("validator", {}).get("kind") != slot.get("validator", {}).get("kind"):
        fail_runtime(
            f"Runtime manifest artifact {lane}.{role} validator does not match the declared slot validator."
        )

    slot_required = bool(slot.get("required", False))
    artifact_present = bool(artifact.get("present", False))
    if slot_required and not artifact_present:
        fail_runtime(f"Missing required {lane} artifact role {role}.")
    if not artifact_present:
        return {
            "role": role,
            "slot": slot,
            "artifact": artifact,
            "path": None,
        }

    relative_path = _normalize_relative_path(
        artifact.get("relative_path"),
        expected_root=lane,
        fail_runtime=fail_runtime,
    )
    artifact_path = runtime_manifest["input_dir"] / relative_path
    if not artifact_path.exists():
        fail_runtime(
            f"Runtime manifest artifact path does not exist for {lane}.{role}: {artifact_path}"
        )

    return {
        "role": role,
        "slot": slot,
        "artifact": artifact,
        "path": artifact_path,
    }


def resolve_scoring_asset_by_role(
    runtime_manifest: dict[str, Any],
    *,
    role: str,
    fail_runtime: Callable[[str], None],
    kind: str | None = None,
) -> dict[str, Any]:
    scoring_assets = runtime_manifest.get("scoring_assets", [])
    matches = [
        asset
        for asset in scoring_assets
        if isinstance(asset, dict) and asset.get("role") == role
    ]
    if len(matches) != 1:
        fail_runtime(
            f"Runtime manifest must contain exactly one scoring asset entry for role {role}."
        )

    asset = matches[0]
    if kind is not None and asset.get("kind") != kind:
        fail_runtime(
            f"Runtime manifest scoring asset {role} must use kind={kind}."
        )

    relative_path = _normalize_relative_path(
        asset.get("relative_path"),
        expected_root=RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME,
        fail_runtime=fail_runtime,
    )
    asset_path = runtime_manifest["input_dir"] / relative_path
    if not asset_path.exists():
        fail_runtime(
            f"Runtime manifest scoring asset path does not exist for role {role}: {asset_path}"
        )

    return {
        "role": role,
        "asset": asset,
        "path": asset_path,
    }


def resolve_program_scoring_asset(
    runtime_manifest: dict[str, Any],
    *,
    fail_runtime: Callable[[str], None],
    supported_abi_versions: set[str] | None = None,
) -> dict[str, Any]:
    scoring_assets = runtime_manifest.get("scoring_assets", [])
    program_assets = [
        asset
        for asset in scoring_assets
        if isinstance(asset, dict) and asset.get("kind") == "program"
    ]

    if len(program_assets) != 1:
        fail_runtime(
            "Runtime manifest must contain exactly one program scoring asset. Next step: compile one deterministic program entrypoint and retry."
        )

    program_asset = program_assets[0]
    abi_version = program_asset.get("abi_version")
    if supported_abi_versions is not None and abi_version not in supported_abi_versions:
        fail_runtime(
            f"Unsupported compiled-program ABI {abi_version}. Next step: use one of {','.join(sorted(supported_abi_versions))}."
        )

    return resolve_scoring_asset_by_role(
        runtime_manifest,
        role=str(program_asset.get("role")),
        fail_runtime=fail_runtime,
        kind="program",
    )
