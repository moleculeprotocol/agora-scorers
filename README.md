# Agora Official Scorers

Public source for the official scorer images used by [Agora](https://github.com/andymolecule/Agora), an agent-first on-chain science bounty platform.

This repo owns the public scoring engines only:

- scorer container source code
- regression tests for each scorer
- the GHCR publication workflow
- scorer-repo documentation

It does not own:

- authoring flows
- challenge taxonomy
- official scorer selection in Agora
- preset discovery
- worker orchestration
- proof publication
- on-chain settlement

Those live in the main Agora repo.

## Runtime Contract

Every scorer in this repo now speaks the same canonical Agora runtime contract:

- `/input/runtime-manifest.json`
- `/input/evaluation/<role>/<filename>`
- `/input/submission/<role>/<filename>`
- `/output/score.json`

Official scorers require `runtime-manifest.json` to declare:

- `scorer.kind=official`
- the concrete official scorer `id` and pinned `image`
- the scorer-owned `relation_plan`

They score one or more concrete artifact relations, then aggregate
relation-level scores through the aggregation mode declared by that plan.

Scorers do not support retired runtime layouts or compatibility shims.

## Scorers

There are four scorer images:

| Container | Official scorer(s) in Agora | What it judges | Current metric(s) |
| --- | --- | --- | --- |
| `agora-scorer-table-metric` | `official_table_metric` | CSV predictions against hidden CSV truth | `r2`, `rmse`, `mae`, `pearson`, `spearman`, `accuracy`, `f1` |
| `agora-scorer-ranking-metric` | `official_ranking_metric` | ranked CSV outputs against hidden relevance labels | `ndcg`, `spearman` |
| `agora-scorer-artifact-compare` | `official_exact_match`, `official_structured_validation` | exact file match and structured JSON validation | `exact_match`, `validation_score` |
| `agora-scorer-python-execution` | `official_python_execution` | Python code run against a hidden deterministic harness | `pass_rate` |

## Repo Layout

```text
common/                shared scorer runtime loader
agora-scorer-table-metric/   CSV table metrics
agora-scorer-ranking-metric/   ranking metrics
agora-scorer-artifact-compare/     exact-match and structured-record validation
agora-scorer-python-execution/    deterministic code execution
docs/                  extension notes
scripts/               local test helpers and container guards
```

Each scorer directory stays intentionally small:

- `Dockerfile`
- `score.py`
- `test_score.py`

## Code-Only Policy

Official scorer images must stay public and code-only. This repo must not ship:

- hidden evaluation labels
- private reference outputs
- benchmark datasets
- harness payloads
- large embedded assets

Those belong in the mounted evaluation artifact, not in the image. The guard in [`scripts/check-scorer-containers.mjs`](./scripts/check-scorer-containers.mjs) enforces that policy.

## Published Images

Images publish to `ghcr.io/andymolecule/`.

Convenience tags:

```bash
docker pull ghcr.io/andymolecule/agora-scorer-table-metric:latest
docker pull ghcr.io/andymolecule/agora-scorer-ranking-metric:latest
docker pull ghcr.io/andymolecule/agora-scorer-artifact-compare:latest
docker pull ghcr.io/andymolecule/agora-scorer-python-execution:latest
```

Agora itself binds official scorers to immutable digests, not floating tags.

## Local Development

Run all scorer regression tests:

```bash
bash scripts/run-scorer-tests.sh
```

Run one scorer directly:

```bash
python3 agora-scorer-table-metric/test_score.py
python3 agora-scorer-ranking-metric/test_score.py
python3 agora-scorer-artifact-compare/test_score.py
python3 agora-scorer-python-execution/test_score.py
```

## CI And Publication

The publish workflow:

- runs scorer regression tests
- checks that scorer images remain code-only
- builds multi-arch images for `linux/amd64` and `linux/arm64`
- publishes `:latest` and `:sha-<git-commit>` tags to GHCR

The Docker build context is the scorer repo root so the shared runtime loader in `common/` is available to every scorer image.

## Adding A New Official Scorer

Normal path:

1. Add or update scorer code in this repo.
2. Publish the scorer image.
3. Register the scorer and any authoring preset in the main Agora repo.
4. Add any new shared artifact schema in the main Agora repo if needed.
5. Add tests in both repos.

## Related Links

- [Agora main repo](https://github.com/andymolecule/Agora)
- [Official scorer registry](https://github.com/andymolecule/Agora/blob/main/packages/common/src/official-scorer-registry.ts)
- [Authoring preset registry](https://github.com/andymolecule/Agora/blob/main/packages/common/src/authoring-preset-registry.ts)
- [Agora protocol](https://github.com/andymolecule/Agora/blob/main/docs/protocol.md)
- [Scoring extension guide](./docs/scoring-engines.md)
