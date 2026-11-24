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

The shared `vX.Y.Z` GitHub Release also ships a matching-version npm `.tgz` and
portable Linux/Windows bundles which **require an installed Node.js 20+ runtime**.
`node-release.json` binds their checksums to the release tag and source commit.
Node publication runs independently of Android signing after the desktop release
has passed its source and installation gates. Source and backend remain separate.

GitHub Packages installation may require authentication and package visibility permissions. A public GitHub repository does not automatically imply an anonymously installable package.

Publishing to a remote npm registry requires `packages:write` permissions
and an authenticated owner GitHub Packages configuration. A packed `.tgz`
uploaded to a GitHub Release is **not** proof of a registry publication.
