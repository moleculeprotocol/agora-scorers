import { DEFAULT_IPFS_GATEWAY } from "./constants.js";
import { cliOptionsSchema, parseWithNextAction } from "./contracts.js";
import { formatError } from "./errors.js";
import { normalizeCid, normalizeGateway } from "./cid.js";
import { replayProof } from "./replay.js";

function usage() {
  return `Usage: agora-replay --proof <cid> [--format json] [--ipfs-gateway <url>] [--expected-proof-hash <0x...>]

Options:
  --proof <cid>                 Public Agora proof bundle CID.
  --format json                 Output format. Only json is supported.
  --ipfs-gateway <url>          IPFS gateway base URL. Defaults to ${DEFAULT_IPFS_GATEWAY}.
  --expected-proof-hash <hex>   Optional on-chain proof hash to compare.
  --work-dir <path>             Optional replay workspace path.
  --keep-workspace              Keep an auto-created replay workspace after the command exits.
  -h, --help                    Print this help text.`;
}

function parseArgs(argv) {
  const raw = {
    format: "json",
    ipfsGateway: DEFAULT_IPFS_GATEWAY,
    keepWorkspace: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "-h" || arg === "--help") {
      return { help: true };
    }
    if (arg === "--keep-workspace") {
      raw.keepWorkspace = true;
      continue;
    }

    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      throw new Error(`${arg} requires a value. Next step: pass ${arg} with a value and retry.`);
    }

    if (arg === "--proof") {
      raw.proof = next;
    } else if (arg === "--format") {
      raw.format = next;
    } else if (arg === "--ipfs-gateway") {
      raw.ipfsGateway = next;
    } else if (arg === "--expected-proof-hash") {
      raw.expectedProofHash = next;
    } else if (arg === "--work-dir") {
      raw.workDir = next;
    } else {
      throw new Error(`Unknown option ${arg}. Next step: run agora-replay --help and retry.`);
    }
    index += 1;
  }

  const parsed = parseWithNextAction(
    cliOptionsSchema,
    raw,
    "CLI options",
    "run agora-replay --help, provide --proof <cid>, and retry.",
  );
  return {
    ...parsed,
    proof: normalizeCid(parsed.proof, "proof CID"),
    ipfsGateway: normalizeGateway(parsed.ipfsGateway),
  };
}

export async function runCli(argv) {
  try {
    const options = parseArgs(argv);
    if (options.help) {
      console.log(usage());
      return;
    }

    const result = await replayProof(options);
    console.log(JSON.stringify(result, null, 2));
    if (result.status !== "matched") {
      process.exitCode = 2;
    }
  } catch (error) {
    console.error(formatError(error));
    process.exitCode = 1;
  }
}
