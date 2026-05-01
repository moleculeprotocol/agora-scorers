# Scoring Extension Guide

## Purpose

How this public scorer image fits into Agora scoring without spreading product
semantics across the API, worker, web app, and runtime image.

This repo targets one canonical V2 scorer runtime contract:

- `/input/runtime-manifest.json`
- `/input/evaluation/<role>/<filename>`
- `/input/submission/<role>/<filename>`
- `/input/scoring_assets/<role>/<filename>`
- `/output/score.json`

The official image in this repo is the stable L5 execution envelope. Challenge
variation belongs in staged scoring assets emitted by the main Agora compiler,
not in new official image names or method-specific image branches.

## Boundary

Agora scoring stays clean when these responsibilities remain separate:

1. `packages/common/src/runtime-profile-registry.ts` in the main repo
   - owns official runtime image identity and runtime limits
2. `apps/api/src/lib/evaluation-materializer.ts` in the main repo
   - owns compilation from evaluation intent to staged scoring assets
3. `packages/scorer/src/pipeline.ts` in the main repo
   - stages files, writes `runtime-manifest.json`, runs Docker
4. This scorer repo
   - owns the public official runtime image code and local runtime tests

This repo should not assume product routing, poster authoring behavior, method
vocabulary, metric vocabulary, aggregator vocabulary, capability discovery, or
proof semantics beyond the mounted runtime contract above.

## Scoring Framework Fit

Agora's scoring model separates five axes:

1. L1 submission shape: owned by the main Agora artifact validators.
2. L2 reference source: owned by the main Agora evaluation bindings.
3. L3 comparison primitive: owned by the main Agora scoring registry and
   surfaced through `GET /api/authoring/capabilities`.
4. L4 composition: owned by the main Agora aggregator registry and compiled
   into staged scoring assets.
5. L5 runtime substrate: owned here as the official deterministic image.

This repo owns only L5 runtime mechanism. It must not copy the L3/L4 catalog
from the main repo. The image receives one staged Python-v1 program asset,
executes it, and requires `/output/score.json`.

Composition is invisible to the image. For a single component, the staged
program can be that component's compiled scoring program. For a composed score,
the staged program can be `l4-composition.py`, with component logic staged as
additional scoring assets. The image still runs one Python-v1 program.

Use the three-lens rule when deciding where a change belongs:

- math truth belongs outside Agora-specific runtime code
- product policy belongs in the main Agora repo
- runtime mechanism belongs in this public image only when it changes how a
  staged program is executed

Canonical discovery lives in the main Agora repo:

- methods, metrics, aggregators, and authoring shapes:
  `GET /api/authoring/capabilities`
- runtime manifest schema:
  `/.well-known/scorer-runtime-manifest.schema.json`
- scorer result schema:
  `/.well-known/scorer-result-schema.schema.json`
- scoring model:
  `docs/product/scoring-layer-invariants.md`
- pattern catalog:
  `docs/product/scoring-pattern-catalog.md`

## File Map

### `common/runtime_manifest.py`

Shared scorer-side runtime loader for the official runtime image.

It owns:

- parsing `/input/runtime-manifest.json`
- resolving role-bound staged artifact paths
- resolving staged scoring-asset paths
- validating runtime profile metadata, final score key, and policies

If the mounted runtime contract changes, update this file first and port every
consumer in the same cut.

### `common/runtime_test_support.py`

Shared local fixture helpers.

It owns:

- staged artifact fixtures for the official runtime
- staged scoring-asset fixtures
- runtime manifest writers for local tests
- canonical score output readers for regression fixtures

### `agora-scorer-compiled/entrypoint.py`

The official runtime entrypoint.

It owns:

- validating `runtime_profile.kind=official`
- validating the official runtime profile id
- discovering the single staged program scoring asset
- discovering the staged `python_v1_runtime_sdk` document asset
- exporting the python-v1 environment
- executing the staged compiled program

It must not re-implement challenge-specific scoring logic or own the
`python-v1` helper SDK.

### `python_v1_runtime_sdk` scoring asset

The helper SDK for compiled programs is a staged scoring asset owned by the
main Agora repo.

It owns:

- stable input/output path helpers
- `load_runtime_context()`
- role-based evaluation/submission/scoring-asset resolution
- deterministic `write_score()`
- submission rejection vs runtime failure helpers

Compiled programs import `agora_runtime` from the staged scoring asset. This
image prepends that asset directory to `PYTHONPATH`; it does not bake a copy of
the SDK.

### `agora-scorer-compiled/test_score.py`

The official runtime regression test.

It should prove:

- canonical official runtime manifest succeeds
- missing staged program asset fails loudly
- non-official runtime manifests are rejected by the official image
- staged compiled programs can import the helper SDK
- compiled programs can reject a submission without masquerading as runtime failure

## Design Rules

- Keep images code-only.
- Keep scorer logic deterministic.
- Keep runtime parsing centralized.
- Keep challenge semantics out of this repo.
- Keep one official image unless the dependency envelope changes materially.
- Keep the compiled-program ABI explicit and stable.
- Keep capability enumeration out of this repo; route to capability discovery.

## Release Rule

If the scorer runtime contract changes, cut straight to the new contract and
roll the official runtime digest forward with the new image. Do not keep
parallel official runtime protocols unless there is an explicit migration
requirement.

## Orchestration vs Execution

Multi-step orchestration and the single-invocation image serve different roles
and live in different repos.

### Pipeline orchestration (main repo)

The main Agora repo pipeline owns scheduling, fan-out, retry, and
proof-of-score publication. It decides when a scorer runs, how many
concurrently, and what to do with the result. This includes worker queue
management, timeout enforcement, and integration with the settlement layer.

### Image execution (this repo)

The image published from this repo executes one staged compiled program per
invocation. It receives mounted inputs via the V2 contract, runs the
deterministic scoring logic, and writes `/output/score.json`. It has no
knowledge of queue depth, retries, or downstream consumers.

### Why the separation matters

Keeping orchestration out of the image means the scorer binary stays
deterministic and reproducible regardless of infrastructure changes. A
scheduler migration, queue backend swap, or retry policy change never touches
the scorer image. Conversely, a scoring logic update never risks breaking
pipeline plumbing.

The publish workflow in this repo (`.github/workflows/publish.yml`) produces
the image and emits a release artifact (`official-runtime-release.json`) with
the explicit handoff fields the main repo needs: `profile_id`, `image_ref`,
`digest`, `tags`, `platforms`, and scorer-repo `commit`. The main repo
deployment pipeline consumes that immutable handoff to update its runtime
profile registry, closing the loop without coupling the two repos' release
cadences.
