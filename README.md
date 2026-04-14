# Agora Scorers

Public source for Agora's scorer-side runtime artifacts.

This repo now owns one official scorer image and the reference kit for
deterministic external runtimes that speak the same mounted contract.

It owns:

- the official compiled runtime image source
- scorer-side runtime manifest helpers
- the python-v1 helper SDK for compiled programs
- scorer regression tests
- GHCR publication workflow
- external scorer reference examples

It does not own:

- poster authoring UX
- challenge taxonomy
- runtime profile selection in Agora
- worker orchestration
- proof publication
- on-chain settlement

Those remain in the main Agora repo.

## Runtime Contract

Every scorer runtime in this repo now speaks the same V2 mounted contract:

- `/input/runtime-manifest.json`
- `/input/evaluation/<role>/<filename>`
- `/input/submission/<role>/<filename>`
- `/input/scoring_assets/<role>/<filename>`
- `/output/score.json`

The runtime manifest declares:

- `runtime_profile`
- `artifact_contract`
- `evaluation_bindings`
- `artifacts`
- `scoring_assets`
- `objective`
- `final_score_key`
- `policies`

The official image does not own metric logic, relation templates, or challenge
taxonomy. It reads compiler-produced scoring assets and executes them. Variation
belongs in the staged program/config bundle, not in image identity.

## Official Runtime

There is one official image:

| Container | Runtime profile id | What it does |
| --- | --- | --- |
| `agora-scorer-compiled` | `official_compiled_runtime` | Executes one staged compiled program plus any staged scoring config/bundles against the mounted runtime manifest |

This image is the official lane for:

- `table_metric`
- `ranking_metric`
- `exact_match`
- `rubric_validation`
- `harness_execution`
- `compiled_program`
- `aggregate`

The image stays stable. The compiler changes the staged `score.py` and related
config per challenge.

## Repo Layout

```text
common/                     shared scorer runtime helpers
agora-scorer-compiled/      official compiled runtime image
examples/                   external scorer reference examples
docs/                       scorer-side extension notes
scripts/                    local test helpers and container guards
```

Shared runtime helpers:

- `common/runtime_manifest.py`
  - V2 runtime manifest parsing
  - role-bound artifact resolution
  - scoring-asset resolution
- `common/runtime_test_support.py`
  - local fixture helpers for official and external tests

Official runtime files:

- `agora-scorer-compiled/entrypoint.py`
  - validates the official runtime profile
  - discovers the staged program scoring asset
  - sets ABI environment variables and executes the staged program
- `agora-scorer-compiled/sdk/agora_runtime.py`
  - helper SDK for compiled programs running under `python-v1`
- `agora-scorer-compiled/test_score.py`
  - scorer regression tests for the official compiled runtime

## Code-Only Policy

Official runtime images must stay public and code-only. This repo must not ship:

- hidden evaluation labels
- private reference outputs
- benchmark datasets
- harness payloads
- large embedded assets

Those belong in mounted evaluation artifacts or scoring assets, not in the
image. The guard in `scripts/check-scorer-containers.mjs` enforces that rule.

## Published Image

The official runtime publishes to `ghcr.io/moleculeprotocol/`.

Convenience tags:

```bash
docker pull ghcr.io/moleculeprotocol/agora-scorer-compiled:latest
docker pull ghcr.io/moleculeprotocol/agora-scorer-compiled:sha-<git-commit>
```

Agora itself must bind the runtime profile to an immutable digest, not a
floating tag.

## Local Development

Run all scorer regression tests:

```bash
bash scripts/run-scorer-tests.sh
```

Run specific tests directly:

```bash
python3 agora-scorer-compiled/test_score.py
python3 common/test_runtime_manifest.py
python3 examples/external-minimal/test_score.py
python3 examples/external-weighted-composite/test_score.py
```

## External Scorer Reference Kit

If you are building a custom external runtime for Agora:

1. Reuse `common/runtime_manifest.py`.
2. Reuse `common/runtime_test_support.py`.
3. Start from one of the examples under `examples/`.
4. Keep scoring deterministic.
5. Write one `/output/score.json`.

Reference examples:

- `examples/external-minimal`
  - smallest external scorer skeleton
  - one evaluation role, one submission role
- `examples/external-weighted-composite`
  - multi-artifact external scorer
  - weighted composite scoring with structured `details`

## CI And Publication

The publish workflow:

- runs scorer regression tests
- checks that the official runtime image stays code-only
- builds multi-arch images for `linux/amd64` and `linux/arm64`
- publishes `:latest` and `:sha-<git-commit>` tags to GHCR

The Docker build context is the repo root so the shared runtime helpers in
`common/` are available to the image.

## Related Links

- [Agora main repo](https://github.com/moleculeprotocol/Agora)
- [Runtime profile registry](https://github.com/moleculeprotocol/Agora/blob/main/packages/common/src/runtime-profile-registry.ts)
- [Poster/scorer V2 contract](https://github.com/moleculeprotocol/Agora/blob/main/docs/specs/poster-scorer-v2-contract.md)
- [Agora protocol](https://github.com/moleculeprotocol/Agora/blob/main/docs/protocol.md)
- [Scoring extension guide](./docs/scoring-engines.md)
