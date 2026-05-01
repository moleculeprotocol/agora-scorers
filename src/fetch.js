import { resolveFetchUrl } from "./cid.js";
import { fail } from "./errors.js";

export async function fetchBytes(uri, gateway) {
  const url = resolveFetchUrl(uri, gateway);
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    fail(`Failed to fetch ${uri}: ${detail}.`, "verify the CID is public and the IPFS gateway is reachable, then retry.", "fetch_failed");
  }

  if (!response.ok) {
    fail(`Failed to fetch ${uri}: HTTP ${response.status}.`, "verify the CID is public and the IPFS gateway is reachable, then retry.", "fetch_failed");
  }
  return new Uint8Array(await response.arrayBuffer());
}

export async function fetchText(uri, gateway) {
  return new TextDecoder("utf-8", { fatal: true }).decode(await fetchBytes(uri, gateway));
}

export async function fetchJson(uri, gateway) {
  const text = await fetchText(uri, gateway);
  try {
    return JSON.parse(text);
  } catch {
    fail(`Fetched ${uri} but it was not valid JSON.`, "verify the proof CID points to an Agora proof bundle and retry.", "invalid_json");
  }
}
