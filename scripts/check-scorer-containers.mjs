import fs from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const maxEmbeddedAssetBytes = 1_000_000;
const disallowedAssetPattern =
  /\.(csv|tsv|jsonl|parquet|arrow|feather|npy|npz|pt|pth|ckpt|onnx|pkl|pickle|joblib|bin|h5|hdf5|tar|tgz|gz|bz2|xz|zip)$/i;

const scorerDirs = [
  "agora-scorer-artifact-compare",
  "agora-scorer-table-metric",
  "agora-scorer-ranking-metric",
  "agora-scorer-python-execution",
];

function fail(message) {
  throw new Error(
    `${message} Next step: keep scorer images code-only and move hidden evaluation artifacts or large assets into the evaluation bundle mounted at runtime.`,
  );
}

function walkFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(fullPath));
      continue;
    }
    if (entry.isFile()) {
      files.push(fullPath);
    }
  }
  return files;
}

function validateDockerfile(dockerfilePath) {
  const dockerfile = fs.readFileSync(dockerfilePath, "utf8");
  const lines = dockerfile.split("\n");

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    if (/^ADD\s+/i.test(line)) {
      fail(
        `Dockerfile ${path.relative(rootDir, dockerfilePath)} uses ADD, which is disallowed for official scorers.`,
      );
    }

    const copyMatch = /^COPY\s+(.+)$/i.exec(line);
    if (!copyMatch) continue;

    const instruction = copyMatch[1]
      .split(/\s+/)
      .filter((part) => !part.startsWith("--"));

    if (instruction.length < 2) continue;

    const sources = instruction.slice(0, -1);
    for (const source of sources) {
      if (source.includes("..")) {
        fail(
          `Dockerfile ${path.relative(rootDir, dockerfilePath)} copies from outside its scorer directory (${source}).`,
        );
      }
      if (disallowedAssetPattern.test(source)) {
        fail(
          `Dockerfile ${path.relative(rootDir, dockerfilePath)} copies dataset-like asset ${source}.`,
        );
      }
    }
  }
}

function validateContainerDir(containerDir) {
  const dockerfilePath = path.join(containerDir, "Dockerfile");
  if (!fs.existsSync(dockerfilePath)) {
    fail(`Missing Dockerfile in ${path.relative(rootDir, containerDir)}.`);
  }

  validateDockerfile(dockerfilePath);

  const files = walkFiles(containerDir);
  for (const filePath of files) {
    const relativePath = path.relative(rootDir, filePath);
    const stats = fs.statSync(filePath);

    if (stats.size > maxEmbeddedAssetBytes) {
      fail(
        `Scorer file ${relativePath} is ${stats.size} bytes, which exceeds the code-only policy threshold of ${maxEmbeddedAssetBytes} bytes.`,
      );
    }

    if (disallowedAssetPattern.test(filePath)) {
      fail(`Scorer directory contains dataset-like asset ${relativePath}.`);
    }
  }
}

for (const name of scorerDirs) {
  const containerDir = path.join(rootDir, name);
  if (!fs.existsSync(containerDir)) {
    fail(`${name}/ directory not found.`);
  }
  validateContainerDir(containerDir);
}

console.log("scorer container guard passed");
