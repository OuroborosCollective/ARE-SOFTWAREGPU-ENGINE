import { runDiagnostics } from "./diagnostics.mjs";
import { acceptedCase } from "./readback.mjs";

const runButton = document.getElementById("run");
const downloadButton = document.getElementById("download");
const progress = document.getElementById("progress");
const version = browser.runtime.getManifest().version;
document.getElementById("version").textContent = `v${version}`;
let finished = null;
let running = false;
const labels = { not_started: "Not tested", running: "Checking", pass: "Pixels verified", fail: "Pixel check failed", error: "Error", timeout: "Timed out", unavailable: "Unavailable" };

function update(report) {
  for (const [name, record] of [["webgl", report.webgl], ["default", report.webgpu.default], ["forceFallback", report.webgpu.forceFallback]]) {
    const badge = document.getElementById(`${name}-status`);
    // A status string alone must never create a passing badge.
    const state = record.status === "pass" && (report.fatalError || !acceptedCase(record)) ? "fail" : record.status;
    badge.textContent = labels[state] ?? "Unknown result";
    badge.dataset.state = state;
    const detail = record.reason ?? record.error?.message ?? (record.readback ? `${record.readback.byteLength.toLocaleString()} bytes checked; ${record.readback.mismatchedPixels} incorrect pixels.` : record.stage ?? "Waiting for this check.");
    document.getElementById(`${name}-detail`).textContent = detail;
  }
  progress.textContent = report.fatalError ? `Check could not finish: ${report.fatalError.message}` : report.complete ? "Checks finished. Results describe this browser session only." : "Checking local graphics APIs… This may take a minute or more.";
  document.getElementById("report").textContent = JSON.stringify(report, null, 2);
}

runButton.addEventListener("click", async () => {
  if (running) return;
  running = true;
  finished = null;
  runButton.disabled = true;
  downloadButton.disabled = true;
  // A fresh canvas prevents previous results or a lost context being reused.
  const canvases = {};
  for (const name of ["webgl", "default", "forceFallback"]) {
    const old = document.getElementById(name);
    const fresh = old.cloneNode(false);
    old.replaceWith(fresh);
    canvases[name] = fresh;
  }
  try {
    const report = await runDiagnostics(canvases, update);
    report.addon = { name: "ARE SoftwareGPU Diagnostics", version };
    finished = report;
    update(report);
    downloadButton.disabled = false;
  } catch (error) {
    progress.textContent = `Check could not finish: ${String(error.message ?? error)}`;
  } finally {
    running = false;
    runButton.disabled = false;
  }
});

downloadButton.addEventListener("click", () => {
  if (!finished || running) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(finished, null, 2) + "\n"], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "are-firefox-graphics-report.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
