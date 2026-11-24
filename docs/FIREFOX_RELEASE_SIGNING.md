# Firefox releases and Mozilla signing

Every checked `main` merge uses the same `vMAJOR.MINOR.PATCH` release as Windows
and Linux. The Firefox companion runs after **Verified GoReleaser release**.
Before it can publish, trusted `main` code verifies the repository, publisher
event, successful publishing jobs, actual tag commit, `main` ancestry,
first-parent version, and the downloaded desktop installers and their receipts.
PR runs and forks cannot reach the release jobs or AMO credentials.

## What each release contains

For version `1.2.50`, the first job publishes:

- `are-softwaregpu-diagnostics-1.2.50-unsigned.xpi`
- `are-softwaregpu-diagnostics-1.2.50-source.zip`
- `firefox-addon-1.2.50-package.json`
- `firefox-addon-1.2.50-SHA256SUMS.txt`

The receipt binds both archives to the exact clean source SHA. The manifest is
staged with `1.2.50`; the tracked development manifest remains unchanged. Every
runtime and source file is checked against that source before upload, and every
published asset is downloaded and compared again. Existing asset names are never
overwritten; a retry accepts only identical bytes. Unsigned GitHub availability
does not indicate AMO approval. Standard Firefox releases require Mozilla signing
for permanent installation, as described in Mozilla's [signing overview](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/).

The add-on is a local graphics diagnostic for desktop Firefox, with no website
permissions or diagnostic network requests. It does not install a native GPU
driver or supply an unavailable browser adapter. Its author is Thomas Markgraf
(pseudonym: OuroborosCollective). The exact PolyForm Noncommercial License 1.0.0
text remains in the package and is submitted as the AMO custom license.

## One-time account setup

The repository secret state is unknown until the workflow checks it. No secret
value is printed. The AMO step reports a boolean for each required name and fails
with `BLOCKED_AMO_CREDENTIALS` when either is unavailable.

1. Use the intended Mozilla Add-ons developer account. Complete any account
   verification and review Mozilla's terms in that account. Account ownership,
   browser sign-in or CAPTCHA cannot be replaced by CI.
2. Generate the API credentials in Mozilla's [developer API key page](https://addons.mozilla.org/developers/addon/api/key/).
   Mozilla documents the issuer/key and secret in its [authentication guide](https://mozilla.github.io/addons-server/topics/api/auth.html).
3. In `OuroborosCollective/ARE-SOFTWAREGPU-ENGINE`, open **Settings → Secrets and
   variables → Actions → New repository secret** and save these two values:

   | Repository secret | Value from Mozilla |
   | --- | --- |
   | `AMO_JWT_ISSUER` | JWT issuer / API key |
   | `AMO_JWT_SECRET` | JWT secret / API secret |

4. Open **Actions → Firefox companion release → Run workflow**, select `main`,
   and enter an existing verified desktop release tag, for example `v1.2.50`.

Do not put credentials in issues, chat, source files, manifests or release
attachments. The workflow exposes them only to the final signing step, after all
source admission gates; tool installation runs beforehand without AMO secrets.

## What Mozilla publication proves

The job uses pinned `web-ext@10.8.0`, **listed** channel, the rebuildable source
ZIP, repository support/source links, and the project homepage
`https://arelogic.space/projects/are-softwaregpu-engine/`. The metadata declares
desktop Firefox only. The [web-ext command reference](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/)
documents listed submissions, source upload and approval waiting. Mozilla's
[Add-ons API](https://mozilla.github.io/addons-server/topics/api/addons.html)
documents custom licenses and the `public`, `unreviewed` and `disabled` states.

The workflow first checks the exact version using authenticated AMO reads. An
already submitted pending version is not submitted again. New submissions wait
up to five minutes in the tool. A pending or rejected version leaves the AMO job
failed with an explicit status; it does not undo the unsigned GitHub release.
After review, rerun the workflow with the same tag.

Success requires AMO to report this exact version in channel `listed` with file
status `public`. CI then downloads the official XPI, verifies its SHA256 against
AMO, and checks that every original runtime byte is preserved. Added files may
only be bounded `META-INF` signature metadata. This is an AMO-authenticated
download and byte comparison; the container check alone is not a cryptographic
certificate verifier. Only then are these additional files published:

- `are-softwaregpu-diagnostics-1.2.50-signed.xpi`
- `firefox-addon-1.2.50-amo.json`
- `firefox-addon-1.2.50-signed-SHA256SUMS.txt`

Missing credentials, an unfinished account, a service error, or pending review
are real blockers. The workflow does not create a substitute signature or claim
a Mozilla listing before the public readback succeeds.

## Rebuild the unsigned XPI

Extract the source ZIP into an empty directory and run from its root:

```sh
python tools/package_firefox_addon.py --version 1.2.50 --output-dir /tmp/are-firefox-rebuild
```

Compare the resulting XPI SHA256 with the release package receipt. The archive
contains original readable source and the dependency-free packaging script.
`--source-sha` is for a clean Git checkout during CI; it is intentionally not used
for extracted source archives. Node contract tests and Python release gate tests
are automated checks; the separate pinned Firefox smoke receipt is the evidence
for actual browser execution.
