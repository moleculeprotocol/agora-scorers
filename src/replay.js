import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import yaml from "yaml";
import {
  DEFAULT_SCORE_TOLERANCE,
  SUPPORTED_PROGRAM_ABI_VERSIONS,
} from "./constants.js";
import {
  challengeSpecSchema,
  parseWithNextAction,
  proofBundleSchema,
  scorerOutputEnvelopeSchema,
  validateScorerResultDetailsAgainstSchema,
} from "./contracts.js";
import { fetchBytes, fetchJson, fetchText } from "./fetch.js";
import { fail } from "./errors.js";
import {
  computeProofInputHashFromFiles,
  hashProofBundleCid,
  sha256File,
} from "./hash.js";
import { resolvePinnedImage, runScorerContainer } from "./docker.js";
import { readRuntimeManifestSchemaSha256 } from "./schema-hash.js";
import { stageReplayWorkspace } from "./stage.js";

function findProgramAbiVersion(programAssets) {
  if (programAssets.length !== 1) {
    fail(
      `Runtime manifest must stage exactly one program asset; found ${programAssets.length}.`,
      "publish one compiled scoring program in the public challenge spec and retry.",
      "invalid_program_assets",
    );
  }
  const abiVersion = programAssets[0].abi_version ?? null;
  if (!abiVersion) {
    fail(
      "Program scoring asset is missing abi_version.",
      "publish the compiled program ABI version and retry.",
      "missing_program_abi",
    );
  }
  return abiVersion;
}

function scoreMatches(actual, expected, tolerance = DEFAULT_SCORE_TOLERANCE) {
  return Math.abs(actual - expected) <= tolerance;
}

function boolMatch(mismatches, key, actual, expected) {
  const match = actual === expected;
  if (!match) {
    mismatches.push({ field: key, expected, actual });
  }
  return match;
}

async function withWorkspace(options, callback) {
  const root = options.workDir
    ? path.resolve(options.workDir)
    : await fs.mkdtemp(path.join(os.tmpdir(), "agora-replay-"));
  const inputDir = path.join(root, "input");
  const outputDir = path.join(root, "output");
  await Promise.all([
    fs.mkdir(inputDir, { recursive: true }),
    fs.mkdir(outputDir, { recursive: true }),
  ]);

  try {
    return await callback({
      root,
      inputDir,
      outputPath: path.join(outputDir, "score.json"),
    });
  } finally {
    if (!options.keepWorkspace && !options.workDir) {
      await fs.rm(root, { recursive: true, force: true });
    }
  }
}

function parseChallengeSpec(text) {
  let parsed;
  try {
    parsed = yaml.parse(text);
  } catch {
    fail(
      "Challenge spec CID did not contain valid YAML.",
      "verify proof.challengeSpecCid points to an Agora pinned challenge spec and retry.",
      "invalid_challenge_spec",
    );
  }
  return parseWithNextAction(
    challengeSpecSchema,
    parsed,
    "challenge spec",
    "verify proof.challengeSpecCid points to a current Agora pinned challenge spec and retry.",
  );
}

function parseScorerOutput(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    fail(
      "Runtime output was not valid JSON.",
      "inspect /output/score.json from the runtime image and retry.",
      "invalid_scorer_output",
    );
  }
  return parseWithNextAction(
    scorerOutputEnvelopeSchema,
    parsed,
    "scorer output",
    "fix the runtime output envelope and retry.",
  );
}

export async function replayProof(options) {
  const runtimeManifestSchemaSha256 = await readRuntimeManifestSchemaSha256();
  const proof = parseWithNextAction(
    proofBundleSchema,
    await fetchJson(options.proof, options.ipfsGateway),
    "proof bundle",
    "use a current public proof CID with challengeSpecCid and replaySubmissionCid fields.",
  );
  const proofHash = hashProofBundleCid(options.proof);
  const proofHashMatches = options.expectedProofHash
    ? proofHash.toLowerCase() === options.expectedProofHash.toLowerCase()
    : null;

  const [challengeSpecText, replayBundleBytes] = await Promise.all([
    fetchText(proof.challengeSpecCid, options.ipfsGateway),
    fetchBytes(proof.replaySubmissionCid, options.ipfsGateway),
  ]);
  const challengeSpec = parseChallengeSpec(challengeSpecText);

  return await withWorkspace(options, async (workspace) => {
    const staged = await stageReplayWorkspace({
      spec: challengeSpec,
      image: proof.containerImageDigest,
      inputDir: workspace.inputDir,
      replayBundleBytes,
      gateway: options.ipfsGateway,
    });
    const programAbiVersion = findProgramAbiVersion(staged.programAssets);
    const abiSupported =
      SUPPORTED_PROGRAM_ABI_VERSIONS.includes(programAbiVersion) &&
      challengeSpec.execution.runtime_profile.supported_program_abi_versions.includes(programAbiVersion);
    if (!abiSupported) {
      fail(
        `Program ABI ${programAbiVersion} is not supported by this replay receiver.`,
        `publish a scorer using one of ${SUPPORTED_PROGRAM_ABI_VERSIONS.join(", ")} and retry.`,
        "unsupported_program_abi",
      );
    }

    const resolvedImageDigest = await resolvePinnedImage(proof.containerImageDigest);
    await runScorerContainer({
      image: proof.containerImageDigest,
      inputDir: workspace.inputDir,
      outputPath: workspace.outputPath,
      limits: challengeSpec.execution.runtime_profile.limits,
    });

    const outputText = await fs.readFile(workspace.outputPath, "utf8");
    const scorerOutput = parseScorerOutput(outputText);
    if (!scorerOutput.ok) {
      fail(
        `Runtime rejected replay input: ${scorerOutput.error}.`,
        "inspect the public proof inputs and challenge spec, then retry.",
        "scorer_rejected_input",
      );
    }

    const schemaValidation = validateScorerResultDetailsAgainstSchema(
      challengeSpec.execution.scorer_result_schema,
      scorerOutput.details,
    );
    if (!schemaValidation.valid) {
      fail(
        `Runtime output details do not match scorer_result_schema: ${schemaValidation.errors.join("; ")}.`,
        "fix the scorer program output shape and retry.",
        "scorer_result_schema_mismatch",
      );
    }

    const actualInputHash = await computeProofInputHashFromFiles(
      workspace.inputDir,
      staged.inputPaths,
    );
    const actualOutputHash = await sha256File(workspace.outputPath);
    const mismatches = [];
    const scoreMatch = scoreMatches(scorerOutput.score, proof.score);
    if (!scoreMatch) {
      mismatches.push({
        field: "score",
        expected: proof.score,
        actual: scorerOutput.score,
      });
    }
    const inputHashMatches = boolMatch(
      mismatches,
      "input_hash",
      actualInputHash,
      proof.inputHash,
    );
    const outputHashMatches = boolMatch(
      mismatches,
      "output_hash",
      actualOutputHash,
      proof.outputHash,
    );
    const containerDigestMatches = boolMatch(
      mismatches,
      "container_image_digest",
      resolvedImageDigest,
      proof.containerImageDigest,
    );
    if (proofHashMatches === false) {
      mismatches.push({
        field: "proof_hash",
        expected: options.expectedProofHash,
        actual: proofHash,
      });
    }

    return {
      status: mismatches.length === 0 ? "matched" : "mismatched",
      score: scorerOutput.score,
      score_matches: scoreMatch,
      proof_cid: options.proof,
      proof_hash: proofHash,
      proof_hash_matches: proofHashMatches,
      challenge_spec_cid: proof.challengeSpecCid,
      replay_submission_cid: proof.replaySubmissionCid,
      runtime_profile_id: challengeSpec.execution.runtime_profile.profile_id,
      image_digest: proof.containerImageDigest,
      runtime_manifest_schema_sha256: runtimeManifestSchemaSha256,
      program_abi_version: programAbiVersion,
      supported_program_abi_versions: SUPPORTED_PROGRAM_ABI_VERSIONS,
      abi_supported: abiSupported,
      input_hash_matches: inputHashMatches,
      output_hash_matches: outputHashMatches,
      container_digest_matches: containerDigestMatches,
      mismatches,
    };
  });
}
