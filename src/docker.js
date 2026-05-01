import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fail } from "./errors.js";

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      });
    });
  });
}

function parseDigest(image) {
  const match = /@sha256:[a-f0-9]{64}$/i.exec(image);
  return match?.[0].slice(1).toLowerCase() ?? null;
}

function parseRepoDigestLine(value) {
  const line = value
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .find((entry) => entry.includes("@sha256:"));
  return line ?? null;
}

async function inspectRepoDigest(image, env) {
  const result = await runCommand(
    "docker",
    ["image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
    { env },
  );
  if (result.code !== 0) {
    return null;
  }
  return parseRepoDigestLine(result.stdout);
}

export async function resolvePinnedImage(image, env = process.env) {
  const expectedDigest = parseDigest(image);
  if (!expectedDigest) {
    fail(
      `Container image ${image} is not digest-pinned.`,
      "use the image digest recorded in the public proof bundle and retry.",
      "image_not_pinned",
    );
  }

  const dockerInfo = await runCommand("docker", ["info"], { env });
  if (dockerInfo.code !== 0) {
    fail(
      "Docker is not available for replay verification.",
      "start Docker, confirm `docker info` succeeds, and retry.",
      "docker_unavailable",
    );
  }

  let repoDigest = await inspectRepoDigest(image, env);
  if (!repoDigest) {
    const pull = await runCommand("docker", ["pull", image], { env });
    if (pull.code !== 0) {
      fail(
        `Failed to pull runtime image ${image}: ${pull.stderr || pull.stdout}`.trim(),
        "verify the official runtime image is anonymously pullable and retry.",
        "docker_pull_failed",
      );
    }
    repoDigest = await inspectRepoDigest(image, env);
  }

  if (!repoDigest) {
    fail(
      `Docker did not report a repo digest for ${image}.`,
      "pull the digest-pinned official image and retry.",
      "docker_digest_missing",
    );
  }

  if (parseDigest(repoDigest) !== expectedDigest) {
    fail(
      `Runtime image digest mismatch: expected ${expectedDigest}, Docker resolved ${repoDigest}.`,
      "remove the stale local image, pull the proof image digest again, and retry.",
      "docker_digest_mismatch",
    );
  }

  return repoDigest;
}

export async function runScorerContainer(input) {
  await fs.mkdir(path.dirname(input.outputPath), { recursive: true });
  await fs.writeFile(input.outputPath, "");

  const name = `agora-replay-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const args = [
    "run",
    "--rm",
    "--network=none",
    "--read-only",
    "--name",
    name,
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--user",
    "65532:65532",
    "--memory",
    input.limits.memory,
    "--cpus",
    input.limits.cpus,
    "--pids-limit",
    String(input.limits.pids),
    "--ulimit",
    "fsize=4194304",
    "--tmpfs",
    "/tmp:size=64m",
    "--tmpfs",
    "/output:size=4194304,uid=65532,gid=65532,mode=700",
    "--mount",
    `type=bind,src=${input.inputDir},dst=/input,readonly`,
    "--mount",
    `type=bind,src=${input.outputPath},dst=/output/score.json`,
    input.image,
  ];

  const result = await runCommand("docker", args, {
    env: {
      ...process.env,
      LANG: "C.UTF-8",
      LC_ALL: "C.UTF-8",
      PYTHONHASHSEED: "0",
      SOURCE_DATE_EPOCH: "0",
      TZ: "UTC",
    },
  });

  if (result.code !== 0) {
    fail(
      `Runtime container failed: ${result.stderr || result.stdout}`.trim(),
      "inspect the public proof inputs and runtime image, then retry.",
      "docker_run_failed",
    );
  }

  return {
    stdout: result.stdout,
    stderr: result.stderr,
  };
}
