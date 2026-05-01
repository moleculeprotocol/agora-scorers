import fs from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const replayDirs = ["bin", "src", "test"];
const forbiddenPatterns = [
  /from\s+["']@agora\//,
  /from\s+["']@agora["']/,
  /require\(["']@agora\//,
  /require\(["']@agora["']\)/,
];

function walkFiles(dir) {
  if (!fs.existsSync(dir)) {
    return [];
  }
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return walkFiles(fullPath);
    }
    return entry.isFile() && /\.(js|mjs|cjs|ts)$/.test(entry.name)
      ? [fullPath]
      : [];
  });
}

for (const dir of replayDirs) {
  for (const filePath of walkFiles(path.join(rootDir, dir))) {
    const source = fs.readFileSync(filePath, "utf8");
    for (const pattern of forbiddenPatterns) {
      if (pattern.test(source)) {
        throw new Error(
          `${path.relative(rootDir, filePath)} imports @agora workspace code. Next step: keep @moleculeagora/agora-replay standalone and copy only public wire contracts needed by third-party replay.`,
        );
      }
    }
  }
}

console.log("agora replay package boundary passed");
