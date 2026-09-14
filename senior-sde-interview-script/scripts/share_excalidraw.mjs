#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import zlib from "node:zlib";

const BACKEND_V2_POST = "https://json.excalidraw.com/api/v2/post/";
const FIREBASE_BUCKET = "excalidraw-room-persistence.appspot.com";

function usage() {
  console.error("Usage: node scripts/share_excalidraw.mjs --input <scene.excalidraw>");
  process.exit(2);
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--input") {
      args.input = argv[++i];
    } else if (arg === "--help" || arg === "-h") {
      usage();
    } else {
      console.error(`Unknown argument: ${arg}`);
      usage();
    }
  }
  if (!args.input) {
    usage();
  }
  return args;
}

function concatBuffers(...buffers) {
  const total =
    4 + buffers.length * 4 + buffers.reduce((sum, buffer) => sum + buffer.length, 0);
  const out = Buffer.alloc(total);
  let cursor = 0;
  out.writeUInt32BE(1, cursor);
  cursor += 4;
  for (const buffer of buffers) {
    out.writeUInt32BE(buffer.length, cursor);
    cursor += 4;
    buffer.copy(out, cursor);
    cursor += buffer.length;
  }
  return out;
}

function base64url(buffer) {
  return Buffer.from(buffer)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function encryptAndCompress(dataBuffer, keyBytes) {
  const deflated = zlib.deflateSync(dataBuffer);
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-128-gcm", keyBytes, iv);
  const encrypted = Buffer.concat([
    cipher.update(deflated),
    cipher.final(),
    cipher.getAuthTag(),
  ]);
  return { iv, encrypted };
}

function compressData(dataBuffer, keyBytes, metadata = null) {
  const encodingMetadataBuffer = Buffer.from(
    JSON.stringify({
      version: 2,
      compression: "pako@1",
      encryption: "AES-GCM",
    }),
  );
  const contentsMetadataBuffer = Buffer.from(JSON.stringify(metadata));
  const contents = concatBuffers(contentsMetadataBuffer, Buffer.from(dataBuffer));
  const { iv, encrypted } = encryptAndCompress(contents, keyBytes);
  return concatBuffers(encodingMetadataBuffer, iv, encrypted);
}

async function postBinary(url, buffer, headers = {}) {
  const response = await fetch(url, {
    method: "POST",
    body: buffer,
    headers: {
      "Content-Type": "application/octet-stream",
      ...headers,
    },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Share upload failed: HTTP ${response.status}`);
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function main() {
  const { input } = parseArgs(process.argv);
  const scene = JSON.parse(fs.readFileSync(input, "utf8"));
  const keyBytes = crypto.randomBytes(16);
  const encryptionKey = base64url(keyBytes);
  const files = scene.files || {};
  const databaseScene = {
    type: scene.type,
    version: scene.version,
    source: scene.source,
    elements: scene.elements,
    appState: scene.appState || {},
  };

  const payload = compressData(
    Buffer.from(JSON.stringify(databaseScene, null, 2), "utf8"),
    keyBytes,
    null,
  );
  const response = await postBinary(BACKEND_V2_POST, payload);
  if (!response.id) {
    throw new Error("Share upload returned no identifier");
  }

  let uploadedFiles = 0;
  for (const [id, file] of Object.entries(files)) {
    const metadata = {
      id,
      mimeType: file.mimeType || "application/octet-stream",
      created: Date.now(),
      lastRetrieved: Date.now(),
    };
    const filePayload = compressData(
      Buffer.from(file.dataURL, "utf8"),
      keyBytes,
      metadata,
    );
    const objectName = `files/shareLinks/${response.id}/${id}`;
    const uploadUrl =
      `https://firebasestorage.googleapis.com/v0/b/${FIREBASE_BUCKET}/o` +
      `?uploadType=media&name=${encodeURIComponent(objectName)}`;
    await postBinary(uploadUrl, filePayload, {
      "Cache-Control": "public, max-age=31536000",
    });
    uploadedFiles += 1;
  }

  process.stdout.write(
    JSON.stringify(
      {
        url: `https://excalidraw.com/#json=${response.id},${encryptionKey}`,
        shareId: response.id,
        files: uploadedFiles,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error("Share upload failed; no scene content or provider response is logged.");
  process.exit(1);
});
