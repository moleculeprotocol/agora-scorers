import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "agora-scorer-ranking-metric" / "score.py"
COMMON_DIR = ROOT_DIR / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_test_support import (
    build_official_scorer,
    stage_runtime_artifact,
    write_runtime_manifest,
)


def load_scorer_module():
    spec = importlib.util.spec_from_file_location("agora_ranking_scorer", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load ranking scorer module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_artifact_contract(
    *,
    submission_id_column: str = "id",
    submission_value_column: str = "score",
    evaluation_id_column: str = "id",
    evaluation_value_column: str = "label",
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
                "description": "Hidden relevance labels",
                "file": {
                    "extension": ".csv",
                    "mime_type": "text/csv",
                    "max_bytes": 4096,
                },
                "validator": {
                    "kind": "csv_columns",
                    "required": [evaluation_id_column, evaluation_value_column],
                    "record_key": evaluation_id_column,
                    "value_field": evaluation_value_column,
                    "allow_extra": True,
                },
            }
        ],
        "submission": [
            {
                "role": "predictions",
                "required": True,
                "description": "Solver rankings",
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


def build_relation_plan(
    *,
    aggregation: str = "mean",
) -> dict:
    return {
        "templates": [
            {
                "kind": "tabular_alignment",
                "cardinality": "many",
                "aggregation": aggregation,
                "evaluation": [
                    {
                        "acceptedValidatorKinds": ["csv_columns"],
                        "requiredFile": {
                            "extension": ".csv",
                            "mimeType": "text/csv",
                        },
                    }
                ],
                "submission": [
                    {
                        "acceptedValidatorKinds": ["csv_columns"],
                        "requiredFile": {
                            "extension": ".csv",
                            "mimeType": "text/csv",
                        },
                    }
                ],
            }
        ]
    }


SCORER = build_official_scorer("official_ranking_metric")


def run_case_with_runtime(
    submission_text: str,
    ground_truth_text: str,
    *,
    artifact_contract: dict | None = None,
    metric: str = "spearman",
    comparator: str = "maximize",
    runtime_manifest: dict | None = None,
):
    module = load_scorer_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-agora-scorer-ranking-metric-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    artifact_contract = artifact_contract or build_artifact_contract()
    evaluation_slot = artifact_contract["evaluation"][0]
    submission_slot = artifact_contract["submission"][0]

    evaluation_artifact = stage_runtime_artifact(
        input_dir,
        lane="evaluation",
        role="reference",
        file_name="reference.csv",
        payload=ground_truth_text,
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
            scorer=SCORER,
            metric=metric,
            comparator=comparator,
            artifact_contract=artifact_contract,
            relation_plan=build_relation_plan(),
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


def run_multi_relation_case():
    module = load_scorer_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-agora-scorer-ranking-metric-multi-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    base_contract = build_artifact_contract()
    artifact_contract = {
        "evaluation": [
            {
                **base_contract["evaluation"][0],
                "role": "reference_a",
            },
            {
                **base_contract["evaluation"][0],
                "role": "reference_b",
            },
        ],
        "submission": [
            {
                **base_contract["submission"][0],
                "role": "predictions_a",
            },
            {
                **base_contract["submission"][0],
                "role": "predictions_b",
            },
        ],
        "relations": [
            {
                "kind": "tabular_alignment",
                "evaluation_role": "reference_a",
                "submission_role": "predictions_a",
            },
            {
                "kind": "tabular_alignment",
                "evaluation_role": "reference_b",
                "submission_role": "predictions_b",
            },
        ],
    }

    staged_artifacts = [
        stage_runtime_artifact(
            input_dir,
            lane="evaluation",
            role="reference_a",
            file_name="reference_a.csv",
            payload="id,label\na,3\nb,2\nc,1\n",
            validator=artifact_contract["evaluation"][0]["validator"],
            mime_type="text/csv",
        ),
        stage_runtime_artifact(
            input_dir,
            lane="evaluation",
            role="reference_b",
            file_name="reference_b.csv",
            payload="id,label\nx,3\ny,2\nz,1\n",
            validator=artifact_contract["evaluation"][1]["validator"],
            mime_type="text/csv",
        ),
        stage_runtime_artifact(
            input_dir,
            lane="submission",
            role="predictions_a",
            file_name="predictions_a.csv",
            payload="id,score\na,3\nb,2\nc,1\n",
            validator=artifact_contract["submission"][0]["validator"],
            mime_type="text/csv",
        ),
        stage_runtime_artifact(
            input_dir,
            lane="submission",
            role="predictions_b",
            file_name="predictions_b.csv",
            payload="id,score\nx,1\ny,2\nz,3\n",
            validator=artifact_contract["submission"][1]["validator"],
            mime_type="text/csv",
        ),
    ]

    write_runtime_manifest(
        input_dir,
        scorer=SCORER,
        metric="spearman",
        comparator="maximize",
        artifact_contract=artifact_contract,
        relation_plan=build_relation_plan(),
        artifacts=staged_artifacts,
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


ground_truth = "id,label\na,3\nb,2\nc,1\n"
perfect_submission = "id,score\na,3\nb,2\nc,1\n"
exit_code, payload = run_case_with_runtime(
    perfect_submission,
    ground_truth,
    metric="spearman",
)
assert exit_code == 0, f"perfect spearman run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["selected_metric"] == "spearman", payload
assert payload["details"]["relation_scores"][0]["details"]["selected_metric"] == "spearman", payload

exit_code, payload = run_case_with_runtime(
    perfect_submission,
    ground_truth,
    metric="ndcg",
)
assert exit_code == 0, f"perfect ndcg run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["selected_metric"] == "ndcg", payload
assert payload["details"]["relation_scores"][0]["details"]["selected_metric"] == "ndcg", payload

partial_submission = "id,score\na,3\nb,2\n"
exit_code, payload = run_case_with_runtime(
    partial_submission,
    ground_truth,
    metric="spearman",
)
assert exit_code == 0, f"partial ranking run should be rejected as invalid, not crash: {exit_code}"
assert payload["ok"] is False, payload
assert "exactly one ranking row" in payload["error"], payload

docking_contract = build_artifact_contract(
    submission_id_column="ligand_id",
    submission_value_column="docking_score",
    evaluation_id_column="ligand_id",
    evaluation_value_column="reference_score",
)
docking_ground_truth = "ligand_id,reference_score\nlig1,-7.3\nlig2,-8.1\n"
docking_submission = "ligand_id,docking_score\nlig1,-7.1\nlig2,-8.0\n"
exit_code, payload = run_case_with_runtime(
    docking_submission,
    docking_ground_truth,
    artifact_contract=docking_contract,
    metric="spearman",
)
assert exit_code == 0, f"docking run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["details"]["selected_metric"] == "spearman", payload
assert payload["details"]["relation_scores"][0]["details"]["selected_metric"] == "spearman", payload

exit_code, payload = run_multi_relation_case()
assert exit_code == 0, f"multi relation ranking run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["details"]["relation_count"] == 2, payload
assert payload["score"] == 0.5, payload
assert payload["details"]["relation_scores"][0]["score"] == 1.0, payload
assert payload["details"]["relation_scores"][1]["score"] == 0.0, payload

invalid_kind_manifest = {
    "kind": "agora_runtime",
    "scorer": SCORER,
    "metric": "spearman",
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
exit_code, payload = run_case_with_runtime(
    perfect_submission,
    ground_truth,
    runtime_manifest=invalid_kind_manifest,
)
assert exit_code == 1, f"invalid manifest kind should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "kind=runtime_manifest" in payload["error"], payload

missing_relation_contract = build_artifact_contract()
missing_relation_contract["relations"] = []
missing_relation_manifest = {
    "kind": "runtime_manifest",
    "scorer": SCORER,
    "metric": "spearman",
    "comparator": "maximize",
    "artifact_contract": missing_relation_contract,
    "relation_plan": build_relation_plan(),
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
exit_code, payload = run_case_with_runtime(
    perfect_submission,
    ground_truth,
    runtime_manifest=missing_relation_manifest,
)
assert exit_code == 1, f"missing relation should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "at least one relation matching template kind=tabular_alignment" in payload["error"], payload

missing_relation_plan_manifest = {
    "kind": "runtime_manifest",
    "scorer": SCORER,
    "metric": "spearman",
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
exit_code, payload = run_case_with_runtime(
    perfect_submission,
    ground_truth,
    runtime_manifest=missing_relation_plan_manifest,
)
assert exit_code == 1, f"missing relation_plan should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "relation_plan is required" in payload["error"], payload

print("ranking scorer runtime tests passed")
