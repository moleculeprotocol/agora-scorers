# Scoring Extension Guide

## Purpose

How to extend the official scoring runtime without spreading logic across the
worker, API, and web app.

This repo targets one canonical scorer runtime contract only:

- `/input/runtime-manifest.json`
- `/input/evaluation/<role>/<filename>`
- `/input/submission/<role>/<filename>`
- `/output/score.json`

## Boundary

Agora scoring stays clean when these responsibilities remain separate:

1. `packages/common/src/official-scorer-registry.ts`
   - owns official scorer image identity and runtime limits
2. `packages/common/src/authoring-preset-registry.ts`
   - owns guided preset discovery for authoring
3. `packages/common/src/authoring-artifact-schemas.ts`
   - owns machine-readable uploaded artifact schemas
4. `packages/scorer/src/pipeline.ts`
   - stages files, writes `runtime-manifest.json`, runs Docker

This scorer repo should only implement the public scorer code and its local
tests. It should not assume product routing or authoring behavior beyond the
runtime contract above.

## File Map

### `common/runtime_contract.py`

Shared scorer-side runtime loader.

It owns:

- parsing `/input/runtime-manifest.json`
- resolving relation declarations
- resolving role-bound staged artifact paths
- normalizing policy defaults

If the runtime contract changes, update this file first and port all scorers in
the same cut.

### `gems-*/score.py`

Each scorer entrypoint owns only scorer-specific logic:

- metric validation
- submission/evaluation contract validation
- deterministic comparison or execution
- writing `/output/score.json`

Do not re-parse runtime config differently in each scorer. Keep the shared
runtime loader as the one scorer-side protocol owner.

### `gems-*/test_score.py`

Each scorer test file should prove:

- canonical runtime manifest succeeds
- invalid runtime manifest kind fails loudly
- missing required scorer relation fails loudly

These are protocol regression tests, not dataset fixtures.

## Adding A New Official Scorer

1. Add the scorer directory in this repo.
2. Reuse `common/runtime_contract.py`.
3. Add `score.py` and `test_score.py`.
4. Add a Dockerfile that builds from the scorer repo root.
5. Publish the image.
6. Register the scorer and any preset in the main Agora repo.

## Design Rules

- Keep images code-only.
- Keep scorer logic deterministic.
- Keep runtime parsing centralized.
- Keep authoring concerns out of this repo.
- Prefer one explicit contract over compatibility shims.

## Release Rule

If the runtime contract changes, cut straight to the new contract and roll the
official scorer digests forward with the new scorer images. Do not keep
parallel runtime protocols unless there is an explicit migration requirement.
