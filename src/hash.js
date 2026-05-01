import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { keccak_256 } from "@noble/hashes/sha3";
import { bytesToHex } from "@noble/hashes/utils";
import { normalizeCid } from "./cid.js";
import { fail } from "./errors.js";

const textEncoder = new TextEncoder();

export function sha256Hex(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export async function sha256File(filePath) {
  return sha256Hex(await fs.readFile(filePath));
}

export function hashProofBundleCid(cid) {
  return `0x${bytesToHex(keccak_256(textEncoder.encode(normalizeCid(cid, "proof CID"))))}`;
}

export function computeProofInputHash(inputHashes) {
  return sha256Hex([...inputHashes].sort().join("|"));
}

export function toPosixRelativePath(rootDir, filePath) {
  const relativePath = path.relative(rootDir, filePath);
  if (
    relativePath.length === 0 ||
    relativePath.startsWith("..") ||
    path.isAbsolute(relativePath)
  ) {
    fail(
      `Proof input ${filePath} is outside staged input root ${rootDir}.`,
      "rebuild the replay workspace from the public proof bundle and retry.",
      "invalid_input_path",
    );
  }
  return relativePath.split(path.sep).join("/");
}

export async function computeProofInputHashFromFiles(rootDir, filePaths) {
  const entries = await Promise.all(
    filePaths.map(async (filePath) => {
      const relativePath = toPosixRelativePath(rootDir, filePath);
      return `${relativePath}:${await sha256File(filePath)}`;
    }),
  );
  return computeProofInputHash(entries);
}
