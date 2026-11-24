// This verifier consumes API readback bytes. It never produces a rendered frame.
export const SIZE = 64;
const POINTS = [[32, 32], [32, 24], [32, 40], [2, 2], [61, 61], [2, 32], [61, 32]];

function expectedPixel(x, row, origin) {
  // Integer edge equations at pixel centers for the fixed clip-space triangle.
  // The doubled vertices are (16,16), (112,16), (64,112). No sample is on an edge.
  const px = 2 * x + 1;
  const py = 2 * (origin === "bottom-left" ? row : SIZE - 1 - row) + 1;
  const inside = py > 16 && 240 - py - 2 * px > 0 && 2 * px - py - 16 > 0;
  return inside ? [255, 0, 0, 255] : [0, 0, 255, 255];
}

export async function readbackEvidence(rgba, origin) {
  if (!(rgba instanceof Uint8Array)) throw new TypeError("Readback must be a Uint8Array");
  if (rgba.byteLength !== SIZE * SIZE * 4) throw new Error("Unexpected RGBA8 readback length");
  if (!["bottom-left", "top-left"].includes(origin)) throw new Error("Unknown row origin");
  const counts = { red: 0, blue: 0, other: 0 };
  let mismatchedPixels = 0;
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      const offset = (y * SIZE + x) * 4;
      const actual = rgba.subarray(offset, offset + 4);
      const expected = expectedPixel(x, y, origin);
      if (!actual.every((value, channel) => value === expected[channel])) mismatchedPixels++;
      if (actual[0] === 255 && actual[1] === 0 && actual[2] === 0 && actual[3] === 255) counts.red++;
      else if (actual[0] === 0 && actual[1] === 0 && actual[2] === 255 && actual[3] === 255) counts.blue++;
      else counts.other++;
    }
  }
  const samples = POINTS.map(([x, y]) => {
    const actual = Array.from(rgba.subarray((y * SIZE + x) * 4, (y * SIZE + x) * 4 + 4));
    const expected = expectedPixel(x, y, origin);
    return { x, y, expected, actual, matches: actual.every((value, channel) => value === expected[channel]) };
  });
  const digest = await crypto.subtle.digest("SHA-256", rgba);
  let binary = "";
  for (let i = 0; i < rgba.length; i += 4096) binary += String.fromCharCode(...rgba.subarray(i, i + 4096));
  return {
    width: SIZE, height: SIZE, rowStrideBytes: SIZE * 4, origin, format: "RGBA8",
    byteLength: rgba.byteLength,
    sha256: Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join(""),
    payloadEncoding: "base64", payloadBase64: btoa(binary),
    samples, counts, mismatchedPixels, matches: mismatchedPixels === 0,
  };
}

export function acceptedCase(record) {
  return record?.status === "pass" && record.readback?.matches === true &&
    record.readback?.byteLength === SIZE * SIZE * 4 && record.readback?.mismatchedPixels === 0 &&
    !["errors", "deviceLost", "contextLoss", "cleanupErrors"].some(key => record[key]?.length) &&
    !record.shaderMessages?.some(message => message.type === "error");
}
