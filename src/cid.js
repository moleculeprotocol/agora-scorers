import { z } from "zod";
import { DEFAULT_IPFS_GATEWAY } from "./constants.js";
import { fail } from "./errors.js";

const nonEmptyStringSchema = z.string().trim().min(1);

export function normalizeCid(value, label = "CID") {
  const parsed = nonEmptyStringSchema.safeParse(value);
  if (!parsed.success) {
    fail(`${label} is required.`, `pass a non-empty ${label.toLowerCase()} and retry.`, "invalid_cid");
  }

  const stripped = parsed.data.replace(/^ipfs:\/\//, "").replace(/^\/+/, "");
  if (!stripped || stripped.includes("://")) {
    fail(`${label} must be an IPFS CID or ipfs:// URI.`, `pass a public ${label.toLowerCase()} and retry.`, "invalid_cid");
  }
  return stripped;
}

export function normalizeGateway(gateway = DEFAULT_IPFS_GATEWAY) {
  const parsed = nonEmptyStringSchema.safeParse(gateway);
  if (!parsed.success) {
    fail("IPFS gateway is required.", "pass --ipfs-gateway with an https URL and retry.", "invalid_gateway");
  }

  const normalized = parsed.data.replace(/\/+$/, "");
  try {
    const url = new URL(normalized);
    if (url.protocol !== "https:" && url.protocol !== "http:") {
      throw new Error("unsupported protocol");
    }
  } catch {
    fail("IPFS gateway must be an http or https URL.", "pass a valid --ipfs-gateway URL and retry.", "invalid_gateway");
  }
  return normalized;
}

export function resolveFetchUrl(uri, gateway) {
  const value = nonEmptyStringSchema.parse(uri);
  if (value.startsWith("ipfs://")) {
    const path = value.slice("ipfs://".length).replace(/^\/+/, "");
    return `${normalizeGateway(gateway)}/ipfs/${path}`;
  }
  if (/^https?:\/\//.test(value)) {
    return value;
  }
  return `${normalizeGateway(gateway)}/ipfs/${normalizeCid(value)}`;
}
