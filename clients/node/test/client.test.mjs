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
    async () => ({status:200, json:async()=>({components:[{}],dependencies:[{}]})}));
  assert.equal(ready.status,"gradio-ready");
  const auth = await checkEndpoint("https://gradio.example.org/",async()=>({status:401}));
  assert.equal(auth.status,"authentication-required");
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async()=>({status:200,json:async()=>({not_gradio:true})})), /NOT_A_GRADIO_CONFIG/);
  await assert.rejects(checkEndpoint("https://gradio.example.org/",
    async()=>({status:302})), /ENDPOINT_UNAVAILABLE_HTTP_302/);
});
test("probe reports unreadable config without printing the response body", () => {
  const cli = fileURLToPath(new URL("../bin/are-gradio.mjs", import.meta.url));
  const fetchStub = 'globalThis.fetch = async () => new Response("invalid config");';
  const result = spawnSync(process.execPath,
    ["--import", "data:text/javascript," + encodeURIComponent(fetchStub),
      cli, "probe", "https://gradio.example.org/"], {encoding: "utf8"});

  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr, "ENDPOINT_CONFIG_UNREADABLE\n");
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
