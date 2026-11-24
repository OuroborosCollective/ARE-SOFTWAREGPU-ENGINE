import {test} from "node:test";
import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {parseEndpoint,checkEndpoint,openEndpoint} from "../bin/are-gradio.mjs";

test("HTTPS is mandatory; no credentials or redirect injection", () => {
  for (const value of ["http://host/", "https://user:pass@host/", "file:///etc/passwd",
    "https://host/?token=secret", "javascript:alert(1)", "https://host/#hash",
    "https://host/other"]) assert.throws(() => parseEndpoint(value));
  assert.equal(parseEndpoint("https://gradio.example.org/").origin, "https://gradio.example.org");
});
test("real contract decoding of Gradio health and authentication states", async () => {
  const ready = await checkEndpoint("https://gradio.example.org/",
    async () => Response.json({components:[{}],dependencies:[{}]}));
  assert.equal(ready.status,"gradio-ready");
  const auth = await checkEndpoint("https://gradio.example.org/",async()=>({status:401}));
  assert.equal(auth.status,"authentication-required");
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async()=>Response.json({not_gradio:true})), /NOT_A_GRADIO_CONFIG/);
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async()=>({status:302})), /ENDPOINT_UNAVAILABLE_HTTP_302/);
});
test("accepts a valid Gradio config at the byte limit", async () => {
  const json = JSON.stringify({components:[{label:"é"}],dependencies:[]});
  const limit = 8 * 1024 * 1024;
  const body = json + " ".repeat(limit - Buffer.byteLength(json));
  const result = await checkEndpoint("https://gradio.example.org/", async () => new Response(body));
  assert.equal(result.component_count, 1);
});
test("rejects and cancels a config stream once decoded bytes exceed the limit", async () => {
  const chunk = new Uint8Array(1024 * 1024);
  let reads = 0;
  let cancelled = false;
  const body = new ReadableStream({
    pull(controller) {
      if (++reads <= 8) controller.enqueue(chunk);
      else if (reads === 9) controller.enqueue(chunk.subarray(0, 1));
      else controller.error(new Error("Read past the size limit"));
    },
    cancel() { cancelled = true; },
  }, {highWaterMark: 0});
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async () => new Response(body, {headers: {"Content-Length": "128"}})),
    {message: "GRADIO_CONFIG_TOO_LARGE"});
  assert.equal(cancelled, true);
});
test("Linux and Windows launch without shell injection",()=>{
  for (const platform of ["win32","linux"]) {
    let used;
    const fake=(cmd,args,opts)=>{used={cmd,args,opts};return {on(){},unref(){}};};
    openEndpoint("https://gradio.example.org/",platform,fake);
    assert.equal(used.opts.shell,false);
    assert.equal(used.args.at(-1),"https://gradio.example.org/");
  }
});

test("probe redacts malformed config parser errors", () => {
  const cli = fileURLToPath(new URL("../bin/are-gradio.mjs", import.meta.url));
  const preload = 'globalThis.fetch = async () => new Response("invalid config");';
  const run = spawnSync(process.execPath,
    ["--import", "data:text/javascript," + encodeURIComponent(preload),
     cli, "probe", "https://gradio.example.org/"], {encoding: "utf8"});
  assert.ifError(run.error);
  assert.equal(run.status, 1);
  assert.equal(run.stdout, "");
  assert.equal(run.stderr, "ENDPOINT_CONFIG_UNREADABLE\\n".replace("\\n", "\n"));
});
test("unreadable config never masks size-limit errors", async () => {
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async () => new Response("not json")), {message:"ENDPOINT_CONFIG_UNREADABLE"});
});
