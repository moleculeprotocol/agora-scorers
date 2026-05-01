import shutil
import tempfile
from pathlib import Path

from runtime_manifest import (
    load_runtime_manifest,
    resolve_artifact_by_role,
    resolve_program_scoring_asset,
    resolve_scoring_asset_by_role,
)
from runtime_test_support import (
    build_official_runtime_profile,
    stage_runtime_artifact,
    stage_scoring_asset,
    write_runtime_manifest,
)


def fail_runtime(message: str) -> None:
    raise RuntimeError(message)


def build_artifact_contract() -> dict:
    return {
        "evaluation": [
            {
                "role": "reference",
                "required": True,
                "description": "Hidden truth bundle",
                "file": {
                    "extension": ".json",
                    "mime_type": "application/json",
                    "max_bytes": 4096,
                },
                "validator": {
                    "kind": "json_document",
                },
            }
        ],
        "submission": [
            {
                "role": "candidate",
                "required": True,
                "description": "Solver candidate bundle",
                "file": {
                    "extension": ".json",
                    "mime_type": "application/json",
                    "max_bytes": 4096,
                },
                "validator": {
                    "kind": "json_document",
                },
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


def make_runtime_manifest(*, runtime_profile: dict, include_program: bool) -> dict:
    workspace = Path(tempfile.mkdtemp(prefix="agora-runtime-manifest-test-"))
    input_dir = workspace / "input"
    input_dir.mkdir()

    artifact_contract = build_artifact_contract()
    reference_artifact = stage_runtime_artifact(
        input_dir,
        lane="evaluation",
        role="reference",
        file_name="reference.json",
        payload='{"score": 1}',
        validator=artifact_contract["evaluation"][0]["validator"],
        mime_type="application/json",
    )
    candidate_artifact = stage_runtime_artifact(
        input_dir,
        lane="submission",
        role="candidate",
        file_name="candidate.json",
        payload='{"score": 1}',
        validator=artifact_contract["submission"][0]["validator"],
        mime_type="application/json",
    )
    scoring_assets = []
    if include_program:
        scoring_assets.append(
            stage_scoring_asset(
                input_dir,
                role="compiled_program",
                kind="program",
                artifact_id="score.py",
                file_name="score.py",
                payload="print('compiled scorer smoke')\n",
                abi_version="python-v1",
                entrypoint="score.py",
            )
        )

    runtime_manifest = write_runtime_manifest(
        input_dir,
        runtime_profile=runtime_profile,
        artifact_contract=artifact_contract,
        artifacts=[reference_artifact, candidate_artifact],
        scoring_assets=scoring_assets,
        evaluation_bindings=[{"role": "reference", "artifact_id": "artifact-ref"}],
        objective="maximize",
        final_score_key="final_score",
    )
    runtime_manifest["workspace"] = workspace
    return runtime_manifest


def test_unknown_runtime_profile_kind_rejected() -> None:
    runtime_profile = {
        **build_official_runtime_profile(),
        "kind": "partner",
    }
    runtime_fixture = make_runtime_manifest(
        runtime_profile=runtime_profile,
        include_program=False,
    )
    workspace = runtime_fixture["workspace"]
    try:
        error = None
        try:
            load_runtime_manifest(
                input_dir=workspace / "input",
                fail_runtime=fail_runtime,
            )
        except RuntimeError as caught:
            error = caught

        assert error is not None
        assert "Unsupported kind in runtime manifest" in str(error)
    finally:
        shutil.rmtree(workspace)


def test_official_program_scoring_asset_resolution() -> None:
    runtime_fixture = make_runtime_manifest(
        runtime_profile=build_official_runtime_profile(),
        include_program=True,
    )
    workspace = runtime_fixture["workspace"]
    try:
        runtime_manifest = load_runtime_manifest(
            input_dir=workspace / "input",
            fail_runtime=fail_runtime,
        )
        assert runtime_manifest["runtime_profile"]["profile_id"] == "official_compiled_runtime"
        program_asset = resolve_program_scoring_asset(
            runtime_manifest,
            fail_runtime=fail_runtime,
            supported_abi_versions={"python-v1"},
        )
        config_error = None
        try:
            resolve_scoring_asset_by_role(
                runtime_manifest,
                role="compiled_config",
                fail_runtime=fail_runtime,
            )
        except RuntimeError as error:
            config_error = error

        assert program_asset["path"] is not None
        assert program_asset["asset"]["artifact_id"] == "score.py"
        assert config_error is not None
        assert "compiled_config" in str(config_error)
    finally:
        shutil.rmtree(workspace)


def main() -> None:
    test_unknown_runtime_profile_kind_rejected()
    test_official_program_scoring_asset_resolution()
    print("runtime manifest tests passed")


if __name__ == "__main__":
    main()
