#!/usr/bin/env node
import { spawn } from "node:child_process";

export function parseEndpoint(raw) {
  if (typeof raw !== "string" || raw.length > 2048) throw new Error("ENDPOINT_INVALID");
  let url;
  try { url = new URL(raw); } catch { throw new Error("ENDPOINT_INVALID"); }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password ||
      url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) {
    throw new Error("ENDPOINT_HTTPS_ROOT_REQUIRED");
  }
  return url;
}
export async function checkEndpoint(raw, fetcher = fetch) {
  const base = parseEndpoint(raw);
  const target = new URL("/config", base);
  const response = await fetcher(target, {method: "GET", signal: AbortSignal.timeout(12000),
    redirect: "manual", headers: {"Accept": "application/json"}});
  if (response.status === 401 || response.status === 403)
    return {endpoint: base.origin, status: "authentication-required", http_status: response.status};
  if (response.status !== 200)
    throw new Error("ENDPOINT_UNAVAILABLE_HTTP_" + response.status);
  const body = await response.json();
  if (!body || !Array.isArray(body.components) || !Array.isArray(body.dependencies))
    throw new Error("NOT_A_GRADIO_CONFIG");
  return {endpoint: base.origin, status: "gradio-ready", http_status: 200,
    component_count: body.components.length};
}
export function openEndpoint(raw, platform = process.platform, launcher = spawn) {
  const target = parseEndpoint(raw).toString();
  let executable, args;
  if (platform === "win32") {
    executable = "rundll32.exe"; args = ["url.dll,FileProtocolHandler", target];
  } else if (platform === "darwin") {
    executable = "open"; args = [target];
  } else if (platform === "linux") {
    executable = "xdg-open"; args = [target];
  } else throw new Error("PLATFORM_UNSUPPORTED");
  const child = launcher(executable, args, {stdio: "ignore", detached: true, shell: false});
  child.on("error", e => console.error("OPEN_FAILED:", e.message));
  child.unref();
  return target;
}
if (process.argv[1] && import.meta.url === new URL("file://" + process.argv[1]).href) {
  const [command, endpoint] = process.argv.slice(2);
  if (!["probe", "open"].includes(command) || !endpoint) {
    console.error("Usage: are-gradio probe|open https://gradio.example.org/");
    process.exitCode = 2;
  } else {
    try {
      if (command === "probe") {
        const result = await checkEndpoint(endpoint);
        console.log(JSON.stringify(result));
      } else {
        console.log(openEndpoint(endpoint));
      }
    } catch (err) {
      console.error(String(err.message || err));
      process.exitCode = 1;
    }
  }
}
