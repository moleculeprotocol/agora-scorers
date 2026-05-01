import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  RUNTIME_MANIFEST_SCHEMA_HASH_PATH,
  RUNTIME_MANIFEST_SCHEMA_PATH,
} from "./constants.js";
import { fail } from "./errors.js";
import { sha256Hex } from "./hash.js";

const PACKAGE_ROOT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

export async function readRuntimeManifestSchemaSha256(rootDir = PACKAGE_ROOT_DIR) {
  const schemaPath = path.join(rootDir, RUNTIME_MANIFEST_SCHEMA_PATH);
  const hashPath = path.join(rootDir, RUNTIME_MANIFEST_SCHEMA_HASH_PATH);
  let schemaBytes;
  let recordedHashText;
  try {
    [schemaBytes, recordedHashText] = await Promise.all([
      fs.readFile(schemaPath),
      fs.readFile(hashPath, "utf8"),
    ]);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    fail(
      `Replay receiver package is missing vendored runtime manifest schema artifacts: ${detail}`,
      "reinstall @moleculeagora/agora-replay and retry.",
      "schema_artifact_missing",
    );
  }
  const computedHash = sha256Hex(schemaBytes);
  const recordedHash = recordedHashText.trim().split(/\s+/)[0];
  if (computedHash !== recordedHash) {
    fail(
      "Vendored runtime manifest schema hash does not match schema/scorer-runtime-manifest.canonical.sha256.",
      "revendor the Agora main canonical schema artifact and retry.",
      "schema_hash_mismatch",
    );
  }
  return computedHash;
}
