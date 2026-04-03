import importlib.util
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "agora-scorer-python-execution" / "score.py"
COMMON_DIR = ROOT_DIR / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from runtime_test_support import stage_runtime_artifact, write_runtime_manifest


def load_executor_module():
    spec = importlib.util.spec_from_file_location("agora_code_executor", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load code executor module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_harness_bundle(path: Path, manifest: dict, files: dict[str, str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agora-harness.json", json.dumps(manifest))
        for relative_path, content in files.items():
            archive.writestr(relative_path, content)


def build_artifact_contract() -> dict:
    relations = [
        {
            "kind": "execute_against",
            "harness_role": "harness",
            "solution_role": "solution",
        }
    ]
    return {
        "evaluation": [
            {
                "role": "harness",
                "required": True,
                "description": "Hidden deterministic execution harness",
                "file": {
                    "extension": ".zip",
                    "mime_type": "application/zip",
                    "max_bytes": 8192,
                },
                "validator": {
                    "kind": "archive_layout",
                    "manifest_file": "agora-harness.json",
                    "required_paths": ["agora-harness.json"],
                    "path_rules": ["bundle must include every referenced test file"],
                },
            }
        ],
        "submission": [
            {
                "role": "solution",
                "required": True,
                "description": "Solver Python solution",
                "file": {
                    "extension": ".py",
                    "mime_type": "text/x-python",
                    "max_bytes": 4096,
                },
                "validator": {"kind": "none"},
            }
        ],
        "relations": relations,
    }


def run_case(
    harness_manifest: dict,
    harness_files: dict[str, str],
    submission_source: str,
    *,
    runtime_manifest: dict | None = None,
):
    module = load_executor_module()
    workspace = Path(tempfile.mkdtemp(prefix="agora-agora-scorer-python-execution-"))
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    artifact_contract = build_artifact_contract()
    evaluation_slot = artifact_contract["evaluation"][0]
    submission_slot = artifact_contract["submission"][0]

    harness_path = input_dir / "evaluation" / "harness" / "harness.zip"
    write_harness_bundle(harness_path, harness_manifest, harness_files)
    harness_bytes = harness_path.read_bytes()
    evaluation_artifact = {
        "lane": "evaluation",
        "role": "harness",
        "required": True,
        "present": True,
        "validator": evaluation_slot["validator"],
        "relative_path": "evaluation/harness/harness.zip",
        "file_name": "harness.zip",
        "mime_type": "application/zip",
        "size_bytes": len(harness_bytes),
        "sha256": hashlib.sha256(harness_bytes).hexdigest(),
    }
    submission_artifact = stage_runtime_artifact(
        input_dir,
        lane="submission",
        role="solution",
        file_name="solution.py",
        payload=submission_source,
        validator=submission_slot["validator"],
        mime_type="text/x-python",
    )

    if runtime_manifest is None:
        write_runtime_manifest(
            input_dir,
            metric="pass_rate",
            comparator="maximize",
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


harness_manifest = {
    "version": "v1",
    "language": "python",
    "timeout_ms": 2000,
    "strip_trailing_whitespace": True,
    "tests": [
        {
            "name": "echo-alpha",
            "stdin_path": "tests/input_01.txt",
            "expected_stdout_path": "tests/output_01.txt",
        },
        {
            "name": "echo-beta",
            "stdin_path": "tests/input_02.txt",
            "expected_stdout_path": "tests/output_02.txt",
        },
    ],
}

harness_files = {
    "tests/input_01.txt": "alpha\n",
    "tests/output_01.txt": "alpha\n",
    "tests/input_02.txt": "beta\n",
    "tests/output_02.txt": "beta\n",
}

passing_submission = """
import sys

print(sys.stdin.read().strip())
"""

exit_code, payload = run_case(
    harness_manifest,
    harness_files,
    passing_submission,
)
assert exit_code == 0, f"pass-rate run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 1.0, payload
assert payload["details"]["comparison_kind"] == "execution_judge", payload
assert payload["details"]["tests_passed"] == 2, payload
assert payload["details"]["selected_metric"] == "pass_rate", payload

failing_submission = """
import sys

print(sys.stdin.read().strip().upper())
"""

exit_code, payload = run_case(
    harness_manifest,
    harness_files,
    failing_submission,
)
assert exit_code == 0, f"failing run should not crash: {exit_code}"
assert payload["ok"] is True, payload
assert payload["score"] == 0.0, payload
assert payload["details"]["tests_passed"] == 0, payload
assert payload["details"]["results"][0]["reason"] == "mismatch", payload

invalid_harness_manifest = {
    "version": "v1",
    "language": "python",
    "tests": [],
}

exit_code, payload = run_case(
    invalid_harness_manifest,
    {},
    passing_submission,
)
assert exit_code == 1, f"invalid harness should fail runtime: {exit_code}"
assert payload["ok"] is False, payload
assert "non-empty tests array" in payload["error"], payload

path_escape_manifest = {
    "version": "v1",
    "language": "python",
    "tests": [
        {
            "name": "escape",
            "stdin_path": "../escape.txt",
            "expected_stdout_path": "tests/output_01.txt",
        }
    ],
}

exit_code, payload = run_case(
    path_escape_manifest,
    harness_files,
    passing_submission,
)
assert exit_code == 1, f"path-escape harness should fail runtime: {exit_code}"
assert payload["ok"] is False, payload
assert "must not escape the harness root" in payload["error"], payload

invalid_kind_manifest = {
    "kind": "agora_runtime",
    "metric": "pass_rate",
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
    harness_manifest,
    harness_files,
    passing_submission,
    runtime_manifest=invalid_kind_manifest,
)
assert exit_code == 1, f"invalid manifest kind should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "kind=runtime_manifest" in payload["error"], payload

missing_relation_contract = build_artifact_contract()
missing_relation_contract["relations"] = []
missing_relation_manifest = {
    "kind": "runtime_manifest",
    "metric": "pass_rate",
    "comparator": "maximize",
    "artifact_contract": missing_relation_contract,
    "evaluation_bindings": [],
    "artifacts": [
        {
            "lane": "evaluation",
            "role": "harness",
            "required": True,
            "present": True,
            "validator": missing_relation_contract["evaluation"][0]["validator"],
            "relative_path": "evaluation/harness/harness.zip",
            "file_name": "harness.zip",
            "mime_type": "application/zip",
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        {
            "lane": "submission",
            "role": "solution",
            "required": True,
            "present": True,
            "validator": missing_relation_contract["submission"][0]["validator"],
            "relative_path": "submission/solution/solution.py",
            "file_name": "solution.py",
            "mime_type": "text/x-python",
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
    harness_manifest,
    harness_files,
    passing_submission,
    runtime_manifest=missing_relation_manifest,
)
assert exit_code == 1, f"missing relation should fail loudly: {exit_code}"
assert payload["ok"] is False, payload
assert "missing relation kind=execute_against" in payload["error"], payload

print("code executor runtime tests passed")
