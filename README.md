# Agora Scorers

Public source for Agora's official scorer runtime image.

This repo owns one official scorer image: the public, deterministic execution
substrate for Agora's compiled scoring programs.

It owns:

- the official compiled runtime image source
- scorer-side runtime manifest helpers
- scorer regression tests
- GHCR publication workflow

It does not own:

- poster authoring UX
- challenge taxonomy
- scoring method, metric, or aggregator vocabulary
- capability discovery
- the python-v1 helper SDK for compiled programs
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

The official image does not own metric logic, relation templates, challenge
taxonomy, or the `python-v1` helper SDK. It reads compiler-produced scoring
assets and executes them. Variation belongs in staged scoring assets, not in
image identity.

Capability enumeration belongs to the main Agora repo. Agents and verifiers
should discover available methods, metrics, aggregators, and authoring shapes
through `GET /api/authoring/capabilities`, not by reading this repo.

## Official Runtime

There is one official image:

| Container | Runtime profile id | What it does |
| --- | --- | --- |
| `agora-scorer-compiled` | `official_compiled_runtime` | Executes one staged compiled program plus any staged scoring config/bundles against the mounted runtime manifest |

The image is the L5 runtime substrate. It does not branch on scoring method,
metric, or aggregator names. The main Agora compiler stages one Python-v1
program per invocation. That program can implement one scoring primitive or a
composition program that calls staged component logic. The image still sees one
program asset and writes one `/output/score.json`.

## Repo Layout

```text
common/                     shared scorer runtime helpers
agora-scorer-compiled/      official compiled runtime image
docs/                       scorer-side extension notes
scripts/                    local test helpers and container guards
```

Shared runtime helpers:

- `common/runtime_manifest.py`
  - V2 runtime manifest parsing
  - role-bound artifact resolution
  - scoring-asset resolution
- `common/runtime_test_support.py`
  - local fixture helpers for official runtime tests

Official runtime files:

- `agora-scorer-compiled/entrypoint.py`
  - validates the official runtime profile
  - discovers the staged program scoring asset
  - discovers the staged `python_v1_runtime_sdk` document asset first in
    `PYTHONPATH`
  - sets ABI environment variables and executes the staged program
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
```

## Canonical Discovery

The main Agora repo owns product and scoring vocabulary. Use these public
surfaces instead of copying capability lists into this repo:

- Methods, metrics, aggregators, and authoring shapes:
  `GET /api/authoring/capabilities`
- Runtime manifest schema:
  `/.well-known/scorer-runtime-manifest.schema.json`
- Scorer result schema:
  `/.well-known/scorer-result-schema.schema.json`
- Product scoring model:
  `docs/product/scoring-layer-invariants.md` in the main Agora repo
- Pattern catalog:
  `docs/product/scoring-pattern-catalog.md` in the main Agora repo

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
