import fs from "node:fs/promises";
import path from "node:path";
import {
  RUNTIME_EVALUATION_ROOT_DIR_NAME,
  RUNTIME_MANIFEST_FILE_NAME,
  RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME,
  RUNTIME_SUBMISSION_ROOT_DIR_NAME,
} from "./constants.js";
import { extractStoredZipArchive } from "./stored-zip.js";
import { fetchBytes } from "./fetch.js";
import { fail } from "./errors.js";
import { sha256Hex } from "./hash.js";

function basename(value) {
  return path.basename(String(value ?? "").trim());
}

function resolveSourceFileName(source, fallbackBaseName, fallbackExtension = "") {
  const explicitFileName = source.file_name?.trim();
  if (explicitFileName) {
    return basename(explicitFileName);
  }
  return `${fallbackBaseName}${fallbackExtension}`;
}

function resolveScoringAssetFileName(source) {
  return resolveSourceFileName(
    source,
    basename(source.entrypoint?.trim() || source.artifact_id.trim() || source.role),
  );
}

function verifyCommitment(input) {
  const actualSize = input.bytes.byteLength;
  const actualSha256 = sha256Hex(input.bytes);
  if (input.sizeBytes !== undefined && actualSize !== input.sizeBytes) {
    fail(
      `${input.label} size mismatch: expected ${input.sizeBytes}, received ${actualSize}.`,
      "use the exact public artifact referenced by the challenge spec and retry.",
      "artifact_size_mismatch",
    );
  }
  if (input.sha256 !== undefined && actualSha256 !== input.sha256) {
    fail(
      `${input.label} SHA-256 mismatch: expected ${input.sha256}, received ${actualSha256}.`,
      "use the exact public artifact referenced by the challenge spec and retry.",
      "artifact_hash_mismatch",
    );
  }
  return { sizeBytes: actualSize, sha256: actualSha256 };
}

function findSlot(contract, lane, role) {
  return contract[lane].find((slot) => slot.role === role) ?? null;
}

function bindReplaySubmissionEntries(spec, entries) {
  const byRole = new Map();
  for (const entry of entries) {
    const parts = entry.relativePath.split("/");
    if (parts[0] !== RUNTIME_SUBMISSION_ROOT_DIR_NAME || parts.length < 3) {
      fail(
        `Replay submission bundle entry ${entry.relativePath} is outside submission/<role>/<file>.`,
        "rebuild the replay submission bundle from Agora's canonical producer and retry.",
        "invalid_replay_bundle",
      );
    }
    const role = parts[1];
    if (!findSlot(spec.execution.artifact_contract, "submission", role)) {
      fail(
        `Replay submission bundle entry ${entry.relativePath} uses undeclared submission role ${role}.`,
        "rebuild the replay submission bundle from the public challenge artifact contract and retry.",
        "invalid_replay_bundle",
      );
    }
    if (byRole.has(role)) {
      fail(
        `Replay submission bundle contains multiple files for role ${role}.`,
        "rebuild the replay submission bundle with one file per submission role and retry.",
        "invalid_replay_bundle",
      );
    }
    byRole.set(role, entry);
  }

  return spec.execution.artifact_contract.submission.map((slot) => {
    const entry = byRole.get(slot.role);
    if (!entry && slot.required) {
      fail(
        `Replay submission bundle is missing required submission role ${slot.role}.`,
        "use a proof bundle that includes the canonical replay submission CID and retry.",
        "missing_submission_artifact",
      );
    }
    return { slot, entry: entry ?? null };
  });
}

function resolvePublicEvaluationArtifact(spec, binding) {
  if (binding.uri) {
    return {
      artifact_id: binding.artifact_id ?? `${binding.role}_evaluation`,
      role: binding.role,
      visibility: "public",
      uri: binding.uri,
    };
  }

  const artifact = spec.artifacts.find(
    (candidate) =>
      candidate.visibility === "public" &&
      candidate.artifact_id === binding.artifact_id &&
      candidate.uri,
  );
  if (!artifact) {
    fail(
      `Evaluation binding ${binding.role} does not resolve to a public artifact URI.`,
      "publish the required evaluation artifact in the public challenge spec or use an auditable public proof bundle.",
      "missing_public_evaluation_artifact",
    );
  }
  return artifact;
}

async function stageBytes(input) {
  await fs.mkdir(path.dirname(input.outputPath), { recursive: true });
  await fs.writeFile(input.outputPath, input.bytes);
  return input.outputPath;
}

async function stageEvaluationArtifacts(spec, inputDir, gateway) {
  const staged = [];
  for (const binding of spec.execution.evaluation_bindings) {
    const slot = findSlot(spec.execution.artifact_contract, "evaluation", binding.role);
    if (!slot) {
      fail(
        `Evaluation binding ${binding.role} is not declared in artifact_contract.evaluation.`,
        "rebuild the public challenge spec with consistent evaluation bindings and retry.",
        "invalid_challenge_spec",
      );
    }
    const artifact = resolvePublicEvaluationArtifact(spec, binding);
    const bytes = await fetchBytes(artifact.uri, gateway);
    const fileName = resolveSourceFileName(
      artifact,
      slot.role,
      slot.file.extension ?? "",
    );
    const relativePath = path.posix.join(
      RUNTIME_EVALUATION_ROOT_DIR_NAME,
      slot.role,
      fileName,
    );
    const outputPath = path.join(inputDir, ...relativePath.split("/"));
    const commitment = verifyCommitment({
      label: `evaluation artifact ${artifact.artifact_id}`,
      bytes,
      sizeBytes: artifact.size_bytes,
      sha256: artifact.sha256,
    });
    await stageBytes({ outputPath, bytes });
    staged.push({
      lane: "evaluation",
      role: slot.role,
      slot,
      source: artifact,
      fileName,
      relativePath,
      outputPath,
      bytes,
      ...commitment,
    });
  }
  return staged;
}

async function stageSubmissionArtifacts(spec, inputDir, replayBundleBytes) {
  const entries = extractStoredZipArchive(replayBundleBytes);
  const assignments = bindReplaySubmissionEntries(spec, entries);
  const staged = [];
  for (const assignment of assignments) {
    if (!assignment.entry) {
      staged.push({
        lane: "submission",
        role: assignment.slot.role,
        slot: assignment.slot,
        present: false,
      });
      continue;
    }
    const fileName = basename(assignment.entry.relativePath);
    const relativePath = path.posix.join(
      RUNTIME_SUBMISSION_ROOT_DIR_NAME,
      assignment.slot.role,
      fileName,
    );
    const outputPath = path.join(inputDir, ...relativePath.split("/"));
    const commitment = verifyCommitment({
      label: `submission artifact ${assignment.slot.role}`,
      bytes: assignment.entry.bytes,
    });
    await stageBytes({ outputPath, bytes: assignment.entry.bytes });
    staged.push({
      lane: "submission",
      role: assignment.slot.role,
      slot: assignment.slot,
      source: null,
      fileName,
      relativePath,
      outputPath,
      bytes: assignment.entry.bytes,
      present: true,
      ...commitment,
    });
  }
  return staged;
}

async function stageScoringAssets(spec, inputDir, gateway) {
  const staged = [];
  for (const source of spec.execution.scoring_asset_sources) {
    const bytes = await fetchBytes(source.uri, gateway);
    const fileName = resolveScoringAssetFileName(source);
    const relativePath = path.posix.join(
      RUNTIME_SCORING_ASSETS_ROOT_DIR_NAME,
      source.role,
      fileName,
    );
    const outputPath = path.join(inputDir, ...relativePath.split("/"));
    const commitment = verifyCommitment({
      label: `scoring asset ${source.artifact_id}`,
      bytes,
      sizeBytes: source.size_bytes,
      sha256: source.sha256,
    });
    await stageBytes({ outputPath, bytes });
    staged.push({
      source,
      fileName,
      relativePath,
      outputPath,
      bytes,
      ...commitment,
    });
  }
  return staged;
}

function buildManifestArtifacts(spec, stagedEvaluation, stagedSubmission) {
  const evaluationByRole = new Map(stagedEvaluation.map((artifact) => [artifact.role, artifact]));
  const submissionByRole = new Map(stagedSubmission.map((artifact) => [artifact.role, artifact]));
  const artifacts = [];

  for (const slot of spec.execution.artifact_contract.evaluation) {
    const mounted = evaluationByRole.get(slot.role);
    if (!mounted && slot.required) {
      fail(
        `Required evaluation role ${slot.role} is not present in the public challenge spec.`,
        "publish a public evaluation artifact for every required evaluation role and retry.",
        "missing_public_evaluation_artifact",
      );
    }
    artifacts.push({
      lane: "evaluation",
      role: slot.role,
      required: slot.required,
      present: Boolean(mounted),
      validator: slot.validator,
      relative_path: mounted?.relativePath ?? null,
      file_name: mounted?.fileName ?? null,
      mime_type: mounted?.source?.mime_type ?? slot.file.mime_type ?? null,
      size_bytes: mounted?.sizeBytes ?? null,
      sha256: mounted?.sha256 ?? null,
    });
  }

  for (const slot of spec.execution.artifact_contract.submission) {
    const mounted = submissionByRole.get(slot.role);
    artifacts.push({
      lane: "submission",
      role: slot.role,
      required: slot.required,
      present: Boolean(mounted?.present),
      validator: slot.validator,
      relative_path: mounted?.relativePath ?? null,
      file_name: mounted?.fileName ?? null,
      mime_type: slot.file.mime_type ?? null,
      size_bytes: mounted?.sizeBytes ?? null,
      sha256: mounted?.sha256 ?? null,
    });
  }

  return artifacts;
}

function buildManifestScoringAssets(stagedScoringAssets) {
  return stagedScoringAssets.map((asset) => ({
    role: asset.source.role,
    kind: asset.source.kind,
    artifact_id: asset.source.artifact_id,
    ...(asset.source.abi_version ? { abi_version: asset.source.abi_version } : {}),
    ...(asset.source.entrypoint ? { entrypoint: asset.source.entrypoint } : {}),
    relative_path: asset.relativePath,
    file_name: asset.fileName,
    size_bytes: asset.sizeBytes,
    sha256: asset.sha256,
  }));
}

function buildRuntimeManifest(input) {
  return {
    kind: "runtime_manifest",
    runtime_profile: {
      ...input.spec.execution.runtime_profile,
      image: input.image,
    },
    artifact_contract: input.spec.execution.artifact_contract,
    evaluation_bindings: input.spec.execution.evaluation_bindings,
    artifacts: input.manifestArtifacts,
    scoring_assets: input.manifestScoringAssets,
    objective: input.spec.execution.objective,
    final_score_key: input.spec.execution.final_score_key,
    scorer_result_schema: input.spec.execution.scorer_result_schema,
    policies: input.spec.execution.policies,
  };
}

export function serializeRuntimeManifest(manifest) {
  return JSON.stringify(manifest, null, 2);
}

export async function stageReplayWorkspace(input) {
  const [stagedEvaluation, stagedSubmission, stagedScoringAssets] = await Promise.all([
    stageEvaluationArtifacts(input.spec, input.inputDir, input.gateway),
    stageSubmissionArtifacts(input.spec, input.inputDir, input.replayBundleBytes),
    stageScoringAssets(input.spec, input.inputDir, input.gateway),
  ]);

  const manifestArtifacts = buildManifestArtifacts(
    input.spec,
    stagedEvaluation,
    stagedSubmission,
  );
  const manifestScoringAssets = buildManifestScoringAssets(stagedScoringAssets);
  const manifest = buildRuntimeManifest({
    spec: input.spec,
    image: input.image,
    manifestArtifacts,
    manifestScoringAssets,
  });
  const runtimeManifestPath = path.join(input.inputDir, RUNTIME_MANIFEST_FILE_NAME);
  await fs.writeFile(runtimeManifestPath, serializeRuntimeManifest(manifest), "utf8");

  return {
    runtimeManifestPath,
    inputPaths: [
      ...stagedEvaluation.map((artifact) => artifact.outputPath),
      ...stagedSubmission.filter((artifact) => artifact.present).map((artifact) => artifact.outputPath),
      ...stagedScoringAssets.map((asset) => asset.outputPath),
      runtimeManifestPath,
    ],
    programAssets: manifestScoringAssets.filter((asset) => asset.kind === "program"),
  };
}
