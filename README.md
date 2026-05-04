# Agora Scorers

Public source for Agora's official scorer runtime images.

This repo owns the public, deterministic execution substrate images for
Agora's compiled scoring programs.

It owns:

- official runtime image source
- scorer-side runtime manifest helpers
- scorer regression tests
- the standalone public replay receiver CLI
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

## Third-Party Replay Receiver

This repo also publishes the standalone receiver for public Agora proof replay:

```bash
npx @moleculeagora/agora-replay --proof <cid> --format json
```

The receiver consumes public proof bundles, fetches the public challenge spec
and replay submission bundle, stages the runtime mounted contract, pulls the
digest-pinned official image anonymously, runs Docker without network access,
and emits a JSON replay result. It does not require cloning the main Agora
monorepo.

The output includes:

- `runtime_manifest_schema_sha256`
- `determinism_env_sha256`
- `supported_program_abi_versions`
- `program_abi_version`
- `score_matches`
- `input_hash_matches`
- `output_hash_matches`
- `container_digest_matches`
- `mismatches`

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

Official images do not own metric logic, relation templates, challenge
taxonomy, or the `python-v1` helper SDK. They read compiler-produced scoring
assets and execute them. Variation belongs in staged scoring assets, not in
image identity.

Capability enumeration belongs to the main Agora repo. Agents and verifiers
should discover available methods, metrics, aggregators, and authoring shapes
through `GET /api/authoring/capabilities`, not by reading this repo.

## Official Runtime

Official images:

| Container | Runtime profile id | What it does |
| --- | --- | --- |
| `agora-scorer-compiled` | `official_compiled_runtime` | Executes one staged compiled program plus any staged scoring config/bundles against the mounted runtime manifest |
| `agora-scorer-rdkit` | `rdkit_python_runtime` | Executes the same Python-v1 mounted contract with RDKit available for deterministic molecule artifact checks |

The runtime profile owns the deterministic child-process environment. The
current official profile pins `LANG`, `LC_ALL`, `PYTHONHASHSEED`,
`SOURCE_DATE_EPOCH`, and `TZ`; replay and publication prove that environment by
its canonical sorted-key JSON SHA-256.

The image is the L5 runtime substrate. It does not branch on scoring method,
metric, or aggregator names. The main Agora compiler stages one Python-v1
program per invocation. That program can implement one scoring primitive or a
composition program that calls staged component logic. The image still sees one
program asset and writes one `/output/score.json`.

`agora-scorer-rdkit` is a scoped dependency envelope, not a broad scientific
Python image. It pins:

- base image:
  `python:3.11.9-slim@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317`
- `rdkit==2025.3.1`
- `numpy==2.4.4`
- `Pillow==12.2.0`

No apt packages, datasets, model weights, notebooks, docking engines, or
scoring-time package installs are added.

## Repo Layout

```text
common/                     shared scorer runtime helpers
agora-scorer-compiled/      official compiled runtime image
agora-scorer-rdkit/         official RDKit dependency-envelope runtime image
bin/                        agora-replay executable entry point
src/                        standalone replay receiver implementation
test/                       replay receiver fixtures and tests
docs/                       scorer-side extension notes
schema/                     vendored Agora main canonical runtime schema
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
  - sets runtime-profile determinism and ABI environment variables before
    executing the staged program
- `agora-scorer-compiled/test_score.py`
  - scorer regression tests for the official compiled runtime
- `agora-scorer-rdkit/Dockerfile`
  - installs only the hash-locked RDKit dependency envelope
  - reuses the compiled runtime entrypoint and staged Python-v1 SDK path
- `agora-scorer-rdkit/requirements.txt`
  - records the exact wheel hashes accepted for linux/amd64 and linux/arm64

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
docker pull ghcr.io/moleculeprotocol/agora-scorer-rdkit:latest
docker pull ghcr.io/moleculeprotocol/agora-scorer-rdkit:sha-<git-commit>
```

Agora itself must bind the runtime profile to an immutable digest, not a
floating tag.

## Local Development

Run all scorer regression tests:

```bash
bash scripts/run-scorer-tests.sh
```

Run replay receiver tests and boundary checks:

```bash
npm ci
npm test
npm run check:replay-boundary
npm run check:release-provenance
npm run check:rdkit-image
```

Release notes for the npm receiver package live in [RELEASING.md](./RELEASING.md).

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

- installs the standalone replay receiver package
- runs replay receiver tests
- checks that the replay receiver does not import Agora workspace packages
- runs scorer regression tests
- rejects retired scorer vocabulary in active public-repo surfaces
- checks that the official runtime image stays code-only
- builds and runs the RDKit image smoke fixture
- verifies the vendored canonical runtime manifest schema hash
- builds multi-arch images for `linux/amd64` and `linux/arm64`
- emits max-mode BuildKit provenance for the pushed image
- publishes a GitHub/Sigstore provenance attestation for the pushed image
  digest
- publishes `:latest` and `:sha-<git-commit>` tags to GHCR
- emits `runtime_manifest_schema_sha256`, `determinism_env_sha256`, and
  `supported_program_abi_versions` in `official-runtime-release.json`
- emits verifier-oriented provenance metadata in
  `official-runtime-release.json`: subject name, subject digest, source
  repository, source ref, source commit, signer workflow, and attestation URL

The Docker build context is the repo root so the shared runtime helpers in
`common/` are available to the image.

Verify an official image's source provenance with the GitHub CLI:

```bash
gh attestation verify \
  oci://ghcr.io/moleculeprotocol/<image-package>@sha256:<digest> \
  --repo moleculeprotocol/agora-scorers \
  --signer-workflow moleculeprotocol/agora-scorers/.github/workflows/publish.yml \
  --source-digest <commit>
```

Use the `digest`, `provenance.subject_name`, `provenance.source_commit`, and
`provenance.signer_workflow` fields from `official-runtime-release.json`.
Agora main digest rotation must reject a release whose provenance does not
match those fields.

## Related Links

- [Agora main repo](https://github.com/moleculeprotocol/Agora)
- [Runtime profile registry](https://github.com/moleculeprotocol/Agora/blob/main/packages/common/src/runtime-profile-registry.ts)
- [Poster/scorer V2 contract](https://github.com/moleculeprotocol/Agora/blob/main/docs/specs/poster-scorer-v2-contract.md)
- [Agora protocol](https://github.com/moleculeprotocol/Agora/blob/main/docs/protocol.md)
- [Scoring extension guide](./docs/scoring-engines.md)
