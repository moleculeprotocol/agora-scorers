import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import yaml from "yaml";
import { SUPPORTED_PROGRAM_ABI_VERSIONS } from "../src/constants.js";
import { challengeSpecSchema } from "../src/contracts.js";
import { replayProof } from "../src/replay.js";
import { readRuntimeManifestSchemaSha256 } from "../src/schema-hash.js";
import { sha256Hex, computeProofInputHashFromFiles } from "../src/hash.js";
import { stageReplayWorkspace } from "../src/stage.js";
import { createStoredZipArchive } from "../src/stored-zip.js";

const IMAGE =
  "ghcr.io/moleculeprotocol/agora-scorer-compiled@sha256:1111111111111111111111111111111111111111111111111111111111111111";
const OTHER_IMAGE =
  "ghcr.io/moleculeprotocol/agora-scorer-compiled@sha256:2222222222222222222222222222222222222222222222222222222222222222";

const encoder = new TextEncoder();
const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

function bytes(value) {
  return encoder.encode(value);
}

async function createTempDir() {
  return await fs.mkdtemp(path.join(os.tmpdir(), "agora-replay-test-"));
}

async function withCwd(cwd, callback) {
  const previousCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await callback();
  } finally {
    process.chdir(previousCwd);
  }
}

function buildSpec(overrides = {}) {
  const evalBytes = bytes("id,target\n1,0.9\n");
  const programBytes = bytes('print("program")\n');
  const sdkBytes = bytes("# python-v1 sdk\n");
  const configBytes = bytes('{"mode":"fixture"}\n');
  const programAbiVersion = overrides.programAbiVersion ?? "python-v1";
  const runtimeSupported =
    overrides.runtimeSupported ?? SUPPORTED_PROGRAM_ABI_VERSIONS;

  const spec = {
    schema_version: 5,
    id: "fixture-challenge",
    execution: {
      runtime_profile: {
        kind: "official",
        profile_id: "official_compiled_runtime",
        image: IMAGE,
        limits: {
          memory: "256m",
          cpus: "1",
          pids: 64,
          timeout_ms: 30000,
        },
        supported_program_abi_versions: runtimeSupported,
      },
      artifact_contract: {
        evaluation: [
          {
            role: "gold",
            required: true,
            description: "Public gold fixture.",
            file: {
              extension: ".csv",
              max_bytes: 1024,
              mime_type: "text/csv",
            },
            validator: { kind: "none" },
          },
        ],
        submission: [
          {
            role: "answer",
            required: true,
            description: "Solver answer fixture.",
            file: {
              extension: ".csv",
              max_bytes: 1024,
              mime_type: "text/csv",
            },
            validator: { kind: "none" },
          },
        ],
        relations: [],
      },
      evaluation_bindings: [
        {
          kind: "artifact",
          role: "gold",
          artifact_id: "gold_fixture",
        },
      ],
      scoring_asset_sources: [
        {
          role: "compiled_program",
          kind: "program",
          artifact_id: "program_fixture",
          abi_version: programAbiVersion,
          entrypoint: "score.py",
          uri: "ipfs://programcid",
          file_name: "score.py",
          size_bytes: programBytes.byteLength,
          sha256: sha256Hex(programBytes),
        },
        {
          role: "python_v1_runtime_sdk",
          kind: "document",
          artifact_id: "sdk_fixture",
          uri: "ipfs://sdkcid",
          file_name: "agora_runtime.py",
          size_bytes: sdkBytes.byteLength,
          sha256: sha256Hex(sdkBytes),
        },
        {
          role: "scoring_config",
          kind: "config",
          artifact_id: "config_fixture",
          uri: "ipfs://configcid",
          file_name: "config.json",
          size_bytes: configBytes.byteLength,
          sha256: sha256Hex(configBytes),
        },
      ],
      objective: "maximize",
      final_score_key: "final_score",
      scorer_result_schema: {
        dimensions: [{ key: "final_score", value_type: "number" }],
        bonuses: [],
        penalties: [],
        summary_fields: [],
        allow_additional_details: true,
      },
      policies: {
        coverage_policy: "ignore",
        duplicate_id_policy: "ignore",
        invalid_value_policy: "ignore",
      },
    },
    artifacts: [
      {
        artifact_id: "gold_fixture",
        role: "gold",
        visibility: "public",
        uri: "ipfs://evalcid",
        file_name: "gold.csv",
        mime_type: "text/csv",
        size_bytes: evalBytes.byteLength,
        sha256: sha256Hex(evalBytes),
      },
    ],
  };

  return {
    spec,
    files: {
      evalcid: evalBytes,
      programcid: programBytes,
      sdkcid: sdkBytes,
      configcid: configBytes,
    },
  };
}

async function buildProofFixture(options = {}) {
  const output =
    options.output ??
    JSON.stringify({
      ok: true,
      score: 0.9,
      details: { final_score: 0.9 },
    });
  const submissionBytes = bytes("id,prediction\n1,0.9\n");
  const replayBundle = createStoredZipArchive([
    {
      relativePath: "submission/answer/answer.csv",
      bytes: submissionBytes,
    },
  ]);
  const { spec, files } = buildSpec(options);
  const tempDir = await createTempDir();
  try {
    const assetRoutes = Object.fromEntries(
      Object.entries(files).map(([cid, content]) => [cid, Buffer.from(content)]),
    );
    const inputHash = await withFetchFixture(assetRoutes, async (gateway) => {
      const inputDir = path.join(tempDir, "input");
      await fs.mkdir(inputDir, { recursive: true });
      const parsedSpec = challengeSpecSchema.parse(yaml.parse(yaml.stringify(spec)));
      const staged = await stageReplayWorkspace({
        spec: parsedSpec,
        image: IMAGE,
        inputDir,
        replayBundleBytes: replayBundle,
        gateway,
      });
      return await computeProofInputHashFromFiles(inputDir, staged.inputPaths);
    });
    const proof = {
      score: options.proofScore ?? 0.9,
      inputHash: options.inputHash ?? inputHash,
      outputHash: options.outputHash ?? sha256Hex(output),
      containerImageDigest: options.image ?? IMAGE,
      challengeSpecCid: "speccid",
      replaySubmissionCid: "replaycid",
      meta: {
        challengeId: "fixture-challenge",
        submissionId: "fixture-submission",
      },
    };
    if (options.omitReplaySubmissionCid) {
      delete proof.replaySubmissionCid;
    }

    return {
      proof,
      output,
      routes: {
        proofcid: Buffer.from(JSON.stringify(proof)),
        speccid: Buffer.from(yaml.stringify(spec)),
        replaycid: Buffer.from(replayBundle),
        ...assetRoutes,
      },
    };
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

async function withFetchFixture(routes, callback) {
  const previousFetch = globalThis.fetch;
  const gateway = "https://fixture.local";
  globalThis.fetch = async (url) => {
    const parsed = new URL(String(url));
    const key = parsed.pathname.replace(/^\/ipfs\//, "");
    const body = routes[key];
    if (!body) {
      return new Response("missing fixture", { status: 404 });
    }
    return new Response(body, { status: 200 });
  };
  try {
    return await callback(gateway);
  } finally {
    globalThis.fetch = previousFetch;
  }
}

async function writeFakeDocker(input) {
  const dir = await createTempDir();
  const binDir = path.join(dir, "bin");
  await fs.mkdir(binDir, { recursive: true });
  const dockerPath = path.join(binDir, "docker");
  const inspectDigest = input.inspectDigest ?? IMAGE;
  await fs.writeFile(
    dockerPath,
    `#!/bin/sh
set -eu
if [ "$1" = "info" ]; then
  exit 0
fi
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  printf '%s\\n' "${inspectDigest}"
  exit 0
fi
if [ "$1" = "pull" ]; then
  exit 0
fi
if [ "$1" = "run" ]; then
  out=""
  for arg in "$@"; do
    case "$arg" in
      type=bind,src=*,dst=/output/score.json)
        out="\${arg#type=bind,src=}"
        out="\${out%,dst=/output/score.json}"
        ;;
    esac
  done
  if [ -z "$out" ]; then
    echo "missing output mount" >&2
    exit 1
  fi
  printf '%s' "$FAKE_DOCKER_OUTPUT" > "$out"
  exit 0
fi
echo "unsupported docker command: $*" >&2
exit 1
`,
    { mode: 0o755 },
  );
  return { dir, binDir };
}

async function withFakeDocker(options, callback) {
  const oldPath = process.env.PATH;
  const oldOutput = process.env.FAKE_DOCKER_OUTPUT;
  const fake = await writeFakeDocker(options);
  process.env.PATH = `${fake.binDir}${path.delimiter}${oldPath}`;
  process.env.FAKE_DOCKER_OUTPUT = options.output;
  try {
    return await callback();
  } finally {
    process.env.PATH = oldPath;
    if (oldOutput === undefined) {
      delete process.env.FAKE_DOCKER_OUTPUT;
    } else {
      process.env.FAKE_DOCKER_OUTPUT = oldOutput;
    }
    await fs.rm(fake.dir, { recursive: true, force: true });
  }
}

async function runFixture(options = {}) {
  const fixture = await buildProofFixture(options);
  return await withFetchFixture(fixture.routes, async (gateway) =>
    withFakeDocker(
      {
        output: fixture.output,
        inspectDigest: options.inspectDigest,
      },
      async () =>
        await replayProof({
          proof: "proofcid",
          ipfsGateway: gateway,
          format: "json",
          keepWorkspace: false,
        }),
    ),
  );
}

test("replays a public proof bundle and emits receiver contract fields", async () => {
  const result = await runFixture();
  assert.equal(result.status, "matched");
  assert.equal(result.score, 0.9);
  assert.equal(result.score_matches, true);
  assert.equal(result.challenge_spec_cid, "speccid");
  assert.equal(result.replay_submission_cid, "replaycid");
  assert.equal(result.runtime_profile_id, "official_compiled_runtime");
  assert.equal(result.image_digest, IMAGE);
  assert.match(result.runtime_manifest_schema_sha256, /^[a-f0-9]{64}$/);
  assert.equal(result.program_abi_version, "python-v1");
  assert.deepEqual(result.supported_program_abi_versions, ["python-v1"]);
  assert.equal(result.abi_supported, true);
  assert.equal(result.input_hash_matches, true);
  assert.equal(result.output_hash_matches, true);
  assert.equal(result.container_digest_matches, true);
  assert.deepEqual(result.mismatches, []);
});

test("replays from an arbitrary user working directory", async () => {
  const userCwd = await createTempDir();
  try {
    const result = await withCwd(userCwd, async () => await runFixture());
    assert.equal(result.status, "matched");
    assert.match(result.runtime_manifest_schema_sha256, /^[a-f0-9]{64}$/);
  } finally {
    await fs.rm(userCwd, { recursive: true, force: true });
  }
});

test("rejects proof bundles without replaySubmissionCid", async () => {
  const fixture = await buildProofFixture({ omitReplaySubmissionCid: true });
  await withFetchFixture(fixture.routes, async (gateway) => {
    await assert.rejects(
      replayProof({
        proof: "proofcid",
        ipfsGateway: gateway,
        format: "json",
        keepWorkspace: false,
      }),
      /replaySubmissionCid/,
    );
  });
});

test("rejects unsupported program ABI versions before running Docker", async () => {
  const fixture = await buildProofFixture({ programAbiVersion: "python-v2" });
  await withFetchFixture(fixture.routes, async (gateway) => {
    await assert.rejects(
      replayProof({
        proof: "proofcid",
        ipfsGateway: gateway,
        format: "json",
        keepWorkspace: false,
      }),
      /Program ABI python-v2 is not supported/,
    );
  });
});

test("rejects stale vendored runtime schema hashes", async () => {
  const rootDir = await createTempDir();
  try {
    await fs.mkdir(path.join(rootDir, "schema"), { recursive: true });
    await fs.writeFile(
      path.join(rootDir, "schema/scorer-runtime-manifest.canonical.schema.json"),
      "{}",
    );
    await fs.writeFile(
      path.join(rootDir, "schema/scorer-runtime-manifest.canonical.sha256"),
      "0000000000000000000000000000000000000000000000000000000000000000  scorer-runtime-manifest.canonical.schema.json\n",
    );
    await assert.rejects(
      readRuntimeManifestSchemaSha256(rootDir),
      /schema hash does not match/,
    );
  } finally {
    await fs.rm(rootDir, { recursive: true, force: true });
  }
});

test("rejects image digest mismatches resolved by Docker", async () => {
  await assert.rejects(
    runFixture({ inspectDigest: OTHER_IMAGE }),
    /Runtime image digest mismatch/,
  );
});

test("reports score mismatches without hiding proof hash checks", async () => {
  const output = JSON.stringify({
    ok: true,
    score: 0.8,
    details: { final_score: 0.8 },
  });
  const result = await runFixture({
    output,
    proofScore: 0.9,
    outputHash: sha256Hex(output),
  });
  assert.equal(result.status, "mismatched");
  assert.equal(result.score_matches, false);
  assert.deepEqual(result.mismatches, [
    {
      field: "score",
      expected: 0.9,
      actual: 0.8,
    },
  ]);
});

test("reports output hash mismatches", async () => {
  const result = await runFixture({
    outputHash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  });
  assert.equal(result.status, "mismatched");
  assert.equal(result.output_hash_matches, false);
  assert.deepEqual(result.mismatches, [
    {
      field: "output_hash",
      expected: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      actual: sha256Hex(
        JSON.stringify({
          ok: true,
          score: 0.9,
          details: { final_score: 0.9 },
        }),
      ),
    },
  ]);
});

let failures = 0;
for (const { name, fn } of tests) {
  try {
    await fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`not ok - ${name}`);
    console.error(error);
  }
}

if (failures > 0) {
  process.exitCode = 1;
}
