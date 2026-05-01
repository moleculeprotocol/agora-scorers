import { fail } from "./errors.js";

function buildCrc32Table() {
  const table = new Uint32Array(256);
  for (let index = 0; index < table.length; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) === 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
}

const CRC32_TABLE = buildCrc32Table();
const ZIP_TEXT_ENCODER = new TextEncoder();
const ZIP_TEXT_DECODER = new TextDecoder("utf-8", { fatal: true });

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    const tableEntry = CRC32_TABLE[(value ^ byte) & 0xff];
    if (tableEntry === undefined) {
      fail("CRC32 lookup table is incomplete.", "rerun with a current verifier package and retry.", "zip_crc32");
    }
    value = tableEntry ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function normalizeZipPath(relativePath) {
  const trimmed = String(relativePath ?? "").trim();
  if (trimmed.length === 0) {
    fail("Stored zip entry path is empty.", "provide a replay bundle with non-empty archive paths and retry.", "zip_path");
  }

  const segments = [];
  for (const rawSegment of trimmed.replaceAll("\\", "/").split("/")) {
    const segment = rawSegment.trim();
    if (segment.length === 0 || segment === ".") {
      continue;
    }
    if (segment === "..") {
      fail(`Stored zip entry path ${relativePath} escapes the archive root.`, "rebuild the replay bundle with relative archive paths and retry.", "zip_path");
    }
    segments.push(segment);
  }

  if (segments.length === 0 || trimmed.startsWith("/")) {
    fail(`Stored zip entry path ${relativePath} escapes the archive root.`, "rebuild the replay bundle with relative archive paths and retry.", "zip_path");
  }
  return segments.join("/");
}

function createByteArray(size) {
  return new Uint8Array(size);
}

function writeUInt16LE(bytes, offset, value) {
  bytes[offset] = value & 0xff;
  bytes[offset + 1] = (value >>> 8) & 0xff;
}

function writeUInt32LE(bytes, offset, value) {
  bytes[offset] = value & 0xff;
  bytes[offset + 1] = (value >>> 8) & 0xff;
  bytes[offset + 2] = (value >>> 16) & 0xff;
  bytes[offset + 3] = (value >>> 24) & 0xff;
}

function concatByteArrays(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const combined = new Uint8Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }
  return combined;
}

export function createStoredZipArchive(entries) {
  const normalizedEntries = entries.map((entry) => ({
    relativePath: normalizeZipPath(entry.relativePath),
    bytes: entry.bytes instanceof Uint8Array ? entry.bytes : new Uint8Array(entry.bytes),
  }));

  const seenPaths = new Set();
  for (const entry of normalizedEntries) {
    if (seenPaths.has(entry.relativePath)) {
      fail(`Stored zip archive contains duplicate path ${entry.relativePath}.`, "make replay bundle archive paths unique and retry.", "zip_duplicate_path");
    }
    seenPaths.add(entry.relativePath);
  }

  const localRecords = [];
  const centralRecords = [];
  let localOffset = 0;

  for (const entry of normalizedEntries.sort((left, right) =>
    left.relativePath.localeCompare(right.relativePath),
  )) {
    const fileNameBytes = ZIP_TEXT_ENCODER.encode(entry.relativePath);
    const fileBytes = entry.bytes;
    const fileCrc32 = crc32(fileBytes);

    const localHeader = createByteArray(30 + fileNameBytes.length);
    writeUInt32LE(localHeader, 0, 0x04034b50);
    writeUInt16LE(localHeader, 4, 20);
    writeUInt16LE(localHeader, 6, 0);
    writeUInt16LE(localHeader, 8, 0);
    writeUInt16LE(localHeader, 10, 0);
    writeUInt16LE(localHeader, 12, 0);
    writeUInt32LE(localHeader, 14, fileCrc32);
    writeUInt32LE(localHeader, 18, fileBytes.length);
    writeUInt32LE(localHeader, 22, fileBytes.length);
    writeUInt16LE(localHeader, 26, fileNameBytes.length);
    writeUInt16LE(localHeader, 28, 0);
    localHeader.set(fileNameBytes, 30);
    localRecords.push(localHeader, fileBytes);

    const centralHeader = createByteArray(46 + fileNameBytes.length);
    writeUInt32LE(centralHeader, 0, 0x02014b50);
    writeUInt16LE(centralHeader, 4, 20);
    writeUInt16LE(centralHeader, 6, 20);
    writeUInt16LE(centralHeader, 8, 0);
    writeUInt16LE(centralHeader, 10, 0);
    writeUInt16LE(centralHeader, 12, 0);
    writeUInt16LE(centralHeader, 14, 0);
    writeUInt32LE(centralHeader, 16, fileCrc32);
    writeUInt32LE(centralHeader, 20, fileBytes.length);
    writeUInt32LE(centralHeader, 24, fileBytes.length);
    writeUInt16LE(centralHeader, 28, fileNameBytes.length);
    writeUInt16LE(centralHeader, 30, 0);
    writeUInt16LE(centralHeader, 32, 0);
    writeUInt16LE(centralHeader, 34, 0);
    writeUInt16LE(centralHeader, 36, 0);
    writeUInt32LE(centralHeader, 38, 0);
    writeUInt32LE(centralHeader, 42, localOffset);
    centralHeader.set(fileNameBytes, 46);
    centralRecords.push(centralHeader);

    localOffset += localHeader.length + fileBytes.length;
  }

  const centralDirectory = concatByteArrays(centralRecords);
  const endOfCentralDirectory = createByteArray(22);
  writeUInt32LE(endOfCentralDirectory, 0, 0x06054b50);
  writeUInt16LE(endOfCentralDirectory, 4, 0);
  writeUInt16LE(endOfCentralDirectory, 6, 0);
  writeUInt16LE(endOfCentralDirectory, 8, normalizedEntries.length);
  writeUInt16LE(endOfCentralDirectory, 10, normalizedEntries.length);
  writeUInt32LE(endOfCentralDirectory, 12, centralDirectory.length);
  writeUInt32LE(endOfCentralDirectory, 16, localOffset);
  writeUInt16LE(endOfCentralDirectory, 20, 0);

  return concatByteArrays([
    ...localRecords,
    centralDirectory,
    endOfCentralDirectory,
  ]);
}

function readByte(bytes, offset) {
  const value = bytes[offset];
  if (value === undefined) {
    fail("Invalid stored ZIP archive: truncated numeric field.", "rebuild the replay bundle and retry.", "zip_truncated");
  }
  return value;
}

function readUInt16LE(bytes, offset) {
  return readByte(bytes, offset) | (readByte(bytes, offset + 1) << 8);
}

function readUInt32LE(bytes, offset) {
  return (
    (readByte(bytes, offset) |
      (readByte(bytes, offset + 1) << 8) |
      (readByte(bytes, offset + 2) << 16) |
      (readByte(bytes, offset + 3) << 24)) >>>
    0
  );
}

export function extractStoredZipArchive(archiveBytes) {
  const bytes =
    archiveBytes instanceof Uint8Array
      ? archiveBytes
      : new Uint8Array(archiveBytes);
  const entries = [];
  const seenPaths = new Set();
  let offset = 0;

  while (offset + 4 <= bytes.byteLength) {
    const signature = readUInt32LE(bytes, offset);
    if (signature === 0x02014b50 || signature === 0x06054b50) {
      break;
    }
    if (signature !== 0x04034b50) {
      fail("Stored zip archive contains an unsupported record.", "rebuild the archive with Agora's canonical stored-zip helper and retry.", "zip_record");
    }
    if (offset + 30 > bytes.byteLength) {
      fail("Stored zip archive ended before a local file header completed.", "rebuild the replay bundle and retry.", "zip_truncated");
    }

    const generalPurposeFlags = readUInt16LE(bytes, offset + 6);
    const compressionMethod = readUInt16LE(bytes, offset + 8);
    const compressedSize = readUInt32LE(bytes, offset + 18);
    const uncompressedSize = readUInt32LE(bytes, offset + 22);
    const fileNameLength = readUInt16LE(bytes, offset + 26);
    const extraLength = readUInt16LE(bytes, offset + 28);

    if ((generalPurposeFlags & 0x0008) !== 0) {
      fail("Stored zip archive uses data descriptors, which Agora does not support.", "rebuild the replay bundle with stored entries and retry.", "zip_descriptor");
    }
    if (compressionMethod !== 0) {
      fail("Stored zip archive uses compression, which Agora does not support for runtime transport.", "rebuild the replay bundle with stored entries and retry.", "zip_compression");
    }
    if (compressedSize !== uncompressedSize) {
      fail("Stored zip archive has mismatched stored sizes.", "rebuild the replay bundle and retry.", "zip_size");
    }

    const dataOffset = offset + 30 + fileNameLength + extraLength;
    const endOffset = dataOffset + compressedSize;
    if (endOffset > bytes.byteLength) {
      fail("Stored zip archive ended before file bytes completed.", "rebuild the replay bundle and retry.", "zip_truncated");
    }

    const fileNameBytes = bytes.slice(offset + 30, offset + 30 + fileNameLength);
    const relativePath = normalizeZipPath(ZIP_TEXT_DECODER.decode(fileNameBytes));
    if (seenPaths.has(relativePath)) {
      fail(`Stored zip archive contains duplicate path ${relativePath}.`, "make replay bundle archive paths unique and retry.", "zip_duplicate_path");
    }

    const fileBytes = bytes.slice(dataOffset, endOffset);
    const expectedCrc32 = readUInt32LE(bytes, offset + 14);
    if (crc32(fileBytes) !== expectedCrc32) {
      fail(`Stored zip archive entry ${relativePath} failed CRC32 validation.`, "rebuild the replay bundle and retry.", "zip_crc32");
    }

    seenPaths.add(relativePath);
    entries.push({ relativePath, bytes: fileBytes });
    offset = endOffset;
  }

  return entries;
}
