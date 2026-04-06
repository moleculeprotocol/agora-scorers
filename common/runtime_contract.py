import json
from pathlib import Path
from typing import Any, Callable

RUNTIME_MANIFEST_FILE_NAME = "runtime-manifest.json"

_COVERAGE_POLICIES = {"reject", "ignore", "penalize"}
_DUPLICATE_ID_POLICIES = {"reject", "ignore"}
_INVALID_VALUE_POLICIES = {"reject", "ignore"}
_COMPARATORS = {"maximize", "minimize"}
_RELATION_CARDINALITIES = {"single", "many"}
_RELATION_AGGREGATIONS = {"single", "mean", "min", "max", "all_or_nothing"}
_RELATION_KINDS = {
    "tabular_alignment",
    "exact_match",
    "execute_against",
    "structured_validation",
}
_VALIDATOR_KINDS = {
    "none",
    "csv_columns",
    "json_document",
    "json_schema",
    "archive_layout",
}


def _require_runtime_scorer(
    runtime_manifest: dict[str, Any],
    *,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    scorer = _require_mapping(runtime_manifest, "scorer", fail_runtime=fail_runtime)
    kind = _require_enum_value(
        scorer,
        "kind",
        allowed_values={"official", "external"},
        fail_runtime=fail_runtime,
    )
    if kind != "official":
        fail_runtime(
            "Official scorer runtime requires scorer.kind=official. Next step: run this image only with an official runtime manifest and retry."
        )

    return {
        "kind": kind,
        "id": _require_non_empty_string(scorer, "id", fail_runtime=fail_runtime),
        "image": _require_non_empty_string(scorer, "image", fail_runtime=fail_runtime),
    }


def _normalize_relative_path(value: Any, *, fail_runtime: Callable[[str], None]) -> Path:
    if not isinstance(value, str) or not value.strip():
        fail_runtime(
            "Runtime manifest present artifacts must include a non-empty relative_path."
        )

    normalized = value.replace("\\", "/").strip()
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail_runtime(
            f"Runtime manifest artifact path must stay within /input. Received: {value}"
        )

    return candidate


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


def _require_relation_artifact_rules(
    template: dict[str, Any],
    lane: str,
    *,
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    rules = _require_list(template, lane, fail_runtime=fail_runtime)
    if len(rules) == 0:
        fail_runtime(f"Runtime manifest relation_plan template {lane} must not be empty.")

    normalized_rules: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            fail_runtime(
                f"Runtime manifest relation_plan template {lane}[{index}] must be an object."
            )
        accepted_validator_kinds = rule.get("acceptedValidatorKinds")
        if (
            not isinstance(accepted_validator_kinds, list)
            or len(accepted_validator_kinds) == 0
            or not all(
                isinstance(kind, str) and kind in _VALIDATOR_KINDS
                for kind in accepted_validator_kinds
            )
        ):
            fail_runtime(
                f"Runtime manifest relation_plan template {lane}[{index}] must declare acceptedValidatorKinds using supported validator kinds."
            )

        required_file = rule.get("requiredFile")
        if required_file is not None and not isinstance(required_file, dict):
            fail_runtime(
                f"Runtime manifest relation_plan template {lane}[{index}].requiredFile must be an object when present."
            )

        normalized_rules.append(
            {
                "acceptedValidatorKinds": list(accepted_validator_kinds),
                "requiredFile": required_file,
            }
        )

    return normalized_rules


def _require_relation_plan(
    runtime_manifest: dict[str, Any],
    *,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    relation_plan = runtime_manifest.get("relation_plan")
    if not isinstance(relation_plan, dict):
        fail_runtime(
            "Runtime manifest relation_plan is required for official scorers. Next step: republish the challenge with a scorer relation plan and retry."
        )

    templates = _require_list(relation_plan, "templates", fail_runtime=fail_runtime)
    if len(templates) == 0:
        fail_runtime("Runtime manifest relation_plan.templates must not be empty.")

    normalized_templates: list[dict[str, Any]] = []
    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            fail_runtime(
                f"Runtime manifest relation_plan.templates[{index}] must be an object."
            )
        kind = _require_enum_value(
            template,
            "kind",
            allowed_values=_RELATION_KINDS,
            fail_runtime=fail_runtime,
        )
        cardinality = _require_enum_value(
            template,
            "cardinality",
            allowed_values=_RELATION_CARDINALITIES,
            fail_runtime=fail_runtime,
        )
        aggregation = _require_enum_value(
            template,
            "aggregation",
            allowed_values=_RELATION_AGGREGATIONS,
            fail_runtime=fail_runtime,
        )
        normalized_templates.append(
            {
                "kind": kind,
                "cardinality": cardinality,
                "aggregation": aggregation,
                "evaluation": _require_relation_artifact_rules(
                    template,
                    "evaluation",
                    fail_runtime=fail_runtime,
                ),
                "submission": _require_relation_artifact_rules(
                    template,
                    "submission",
                    fail_runtime=fail_runtime,
                ),
            }
        )

    return {"templates": normalized_templates}


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

    scorer = _require_runtime_scorer(
        runtime_manifest,
        fail_runtime=fail_runtime,
    )
    artifact_contract = _require_mapping(
        runtime_manifest,
        "artifact_contract",
        fail_runtime=fail_runtime,
    )
    evaluation_slots = _require_list(
        artifact_contract,
        "evaluation",
        fail_runtime=fail_runtime,
    )
    submission_slots = _require_list(
        artifact_contract,
        "submission",
        fail_runtime=fail_runtime,
    )
    artifacts = _require_list(
        runtime_manifest,
        "artifacts",
        fail_runtime=fail_runtime,
    )
    relations = artifact_contract.get("relations", [])
    if not isinstance(relations, list):
        fail_runtime("Runtime manifest artifact_contract.relations must be an array.")

    metric = _require_non_empty_string(
        runtime_manifest,
        "metric",
        fail_runtime=fail_runtime,
    )
    comparator = _require_enum_value(
        runtime_manifest,
        "comparator",
        allowed_values=_COMPARATORS,
        fail_runtime=fail_runtime,
    )
    evaluation_bindings = _require_list(
        runtime_manifest,
        "evaluation_bindings",
        fail_runtime=fail_runtime,
    )
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
    relation_plan = _require_relation_plan(
        runtime_manifest,
        fail_runtime=fail_runtime,
    )

    return {
        "metric": metric,
        "comparator": comparator,
        "scorer": scorer,
        "artifact_contract": artifact_contract,
        "evaluation_slots": evaluation_slots,
        "submission_slots": submission_slots,
        "artifacts": artifacts,
        "evaluation_bindings": evaluation_bindings,
        "relation_plan": relation_plan,
        "policies": {
            "coverage_policy": coverage_policy,
            "duplicate_id_policy": duplicate_id_policy,
            "invalid_value_policy": invalid_value_policy,
        },
        "input_dir": input_dir,
        "runtime_manifest_path": runtime_manifest_path,
    }


def list_relation_evaluation_roles(relation: dict[str, Any]) -> list[str]:
    kind = relation.get("kind")
    if kind in {"tabular_alignment", "exact_match", "structured_validation"}:
        value = relation.get("evaluation_role")
        return [value] if isinstance(value, str) else []
    if kind == "execute_against":
        value = relation.get("harness_role")
        return [value] if isinstance(value, str) else []
    return []


def list_relation_submission_roles(relation: dict[str, Any]) -> list[str]:
    kind = relation.get("kind")
    if kind in {"tabular_alignment", "exact_match", "structured_validation"}:
        value = relation.get("submission_role")
        return [value] if isinstance(value, str) else []
    if kind == "execute_against":
        value = relation.get("solution_role")
        return [value] if isinstance(value, str) else []
    return []


def describe_relation(relation: dict[str, Any]) -> str:
    kind = relation.get("kind", "unknown")
    evaluation_roles = ",".join(list_relation_evaluation_roles(relation))
    submission_roles = ",".join(list_relation_submission_roles(relation))
    return f"{kind}:{evaluation_roles}->{submission_roles}"


def match_relation_to_template(
    relation: dict[str, Any],
    template: dict[str, Any],
) -> bool:
    return (
        relation.get("kind") == template.get("kind")
        and len(list_relation_evaluation_roles(relation))
        == len(template["evaluation"])
        and len(list_relation_submission_roles(relation))
        == len(template["submission"])
    )


def require_relation_plan_template(
    runtime_manifest: dict[str, Any],
    *,
    kind: str,
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    templates = runtime_manifest["relation_plan"]["templates"]
    matches = [template for template in templates if template["kind"] == kind]
    if len(matches) != 1:
        fail_runtime(
            f"Runtime manifest relation_plan must contain exactly one template for relation kind {kind}."
        )
    return matches[0]


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


def _resolve_runtime_artifact_by_role(
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


def _validate_relation_artifact(
    *,
    lane: str,
    role: str,
    rule: dict[str, Any],
    artifact: dict[str, Any],
    fail_runtime: Callable[[str], None],
) -> None:
    validator_kind = artifact["slot"].get("validator", {}).get("kind")
    if validator_kind not in rule["acceptedValidatorKinds"]:
        fail_runtime(
            f"Runtime manifest relation_plan rejects {lane} role {role} with validator.kind={validator_kind}."
        )

    required_file = rule.get("requiredFile")
    if not isinstance(required_file, dict):
        return

    required_extension = required_file.get("extension")
    if required_extension and artifact["slot"].get("file", {}).get("extension") != required_extension:
        fail_runtime(
            f"Runtime manifest relation_plan requires {lane} role {role} to use extension {required_extension}."
        )

    required_mime_type = required_file.get("mimeType")
    if required_mime_type and artifact["slot"].get("file", {}).get("mime_type") != required_mime_type:
        fail_runtime(
            f"Runtime manifest relation_plan requires {lane} role {role} to use mime_type {required_mime_type}."
        )


def list_matching_relations(
    runtime_manifest: dict[str, Any],
    *,
    template: dict[str, Any],
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    relations = runtime_manifest["artifact_contract"].get("relations", [])
    matches = [
        relation
        for relation in relations
        if isinstance(relation, dict) and match_relation_to_template(relation, template)
    ]

    if len(matches) == 0:
        fail_runtime(
            f"Runtime manifest must contain at least one relation matching template kind={template['kind']}."
        )

    cardinality = template["cardinality"]
    if cardinality == "single" and len(matches) != 1:
        fail_runtime(
            f"Runtime manifest relation_plan requires exactly one {template['kind']} relation."
        )

    return matches


def resolve_relation_artifact_set(
    runtime_manifest: dict[str, Any],
    *,
    relation: dict[str, Any],
    template: dict[str, Any],
    fail_runtime: Callable[[str], None],
) -> dict[str, Any]:
    evaluation_roles = list_relation_evaluation_roles(relation)
    submission_roles = list_relation_submission_roles(relation)

    evaluation_artifacts = []
    for index, role in enumerate(evaluation_roles):
        artifact = _resolve_runtime_artifact_by_role(
            runtime_manifest,
            lane="evaluation",
            role=role,
            fail_runtime=fail_runtime,
        )
        _validate_relation_artifact(
            lane="evaluation",
            role=role,
            rule=template["evaluation"][index],
            artifact=artifact,
            fail_runtime=fail_runtime,
        )
        evaluation_artifacts.append(artifact)

    submission_artifacts = []
    for index, role in enumerate(submission_roles):
        artifact = _resolve_runtime_artifact_by_role(
            runtime_manifest,
            lane="submission",
            role=role,
            fail_runtime=fail_runtime,
        )
        _validate_relation_artifact(
            lane="submission",
            role=role,
            rule=template["submission"][index],
            artifact=artifact,
            fail_runtime=fail_runtime,
        )
        submission_artifacts.append(artifact)

    return {
        "relation": relation,
        "evaluation": evaluation_artifacts,
        "submission": submission_artifacts,
    }


def resolve_relation_artifact_sets(
    runtime_manifest: dict[str, Any],
    *,
    template: dict[str, Any],
    fail_runtime: Callable[[str], None],
) -> list[dict[str, Any]]:
    return [
        resolve_relation_artifact_set(
            runtime_manifest,
            relation=relation,
            template=template,
            fail_runtime=fail_runtime,
        )
        for relation in list_matching_relations(
            runtime_manifest,
            template=template,
            fail_runtime=fail_runtime,
        )
    ]


def aggregate_relation_scores(
    relation_scores: list[float],
    *,
    aggregation: str,
    fail_runtime: Callable[[str], None],
) -> float:
    if len(relation_scores) == 0:
        fail_runtime("Cannot aggregate an empty relation score set.")

    if aggregation == "single":
        if len(relation_scores) != 1:
            fail_runtime(
                "relation_plan aggregation=single requires exactly one relation score."
            )
        return relation_scores[0]

    if aggregation == "mean":
        return sum(relation_scores) / len(relation_scores)

    if aggregation == "min":
        return min(relation_scores)

    if aggregation == "max":
        return max(relation_scores)

    if aggregation == "all_or_nothing":
        return 1.0 if all(score == 1.0 for score in relation_scores) else 0.0

    fail_runtime(
        f"Unsupported relation_plan aggregation {aggregation}. Next step: use one of {','.join(sorted(_RELATION_AGGREGATIONS))}."
    )
