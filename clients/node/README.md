# ARE SoftwareGPU Gradio client (Node.js)

A separate **read-only** Node 20+ package for Linux, Windows and macOS.
This package does not contain the Python/C++ renderer. It checks the
actual `/config` route of a user-supplied HTTPS Gradio instance and
opens the website in your system browser. Authentication-required (401/403)
is reported honestly instead of inventing a successful remote renderer test.

```sh
npm install -g @ouroboroscollective/softwaregpu-gradio-client --registry=https://npm.pkg.github.com
are-gradio probe https://your-real-gradio.example/
are-gradio open https://your-real-gradio.example/
```

The SHA-bound GitHub Release also ships npm `.tgz` and portable Linux/Windows
bundles with their own Node runtime. Source and backend remain separate.

Publishing to a remote npm registry requires `packages:write` permissions
and an authenticated owner GitHub Packages configuration. A packed `.tgz`
uploaded to a GitHub Release is **not** proof of a registry publication.
