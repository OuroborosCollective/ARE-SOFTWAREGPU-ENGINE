# Android companion releases and permanent signing

The Android deliverable is the existing HTTPS Gradio companion, packaged as
`ARE-SoftwareGPU-X.Y.Z-android-companion.apk`. It opens a configured HTTPS test
server. It does not embed the Python/C++ renderer or install a GPU driver.

After a verified desktop release, the Android workflow publishes into the same
`vX.Y.Z` GitHub Release. Admission checks the actual publisher jobs, immutable tag
commit, full first-parent version, main ancestry, and downloaded Windows/Linux
installer evidence before a signing job can start. APK publication additionally
requires real signature verification and an emulator install, activity launch,
welcome UI check, installed-APK byte readback and uninstall. CI test keys are
explicitly labelled and their APKs are only workflow artifacts.

## One-time owner setup

The repository needs these four Actions secrets. Their current presence and
correctness must be established by the workflow; source code alone proves neither.

| Secret | Value |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | One-line base64 encoding of the permanent JKS keystore |
| `ANDROID_KEYSTORE_PASSWORD` | Password opening that keystore |
| `ANDROID_KEY_ALIAS` | Alias of the permanent signing key |
| `ANDROID_KEY_PASSWORD` | Password for that private key |

Use JDK 17+ and an already authenticated GitHub CLI account allowed to manage
repository secrets. Run this locally from the checked-out repository, choosing a
secure path outside it:

```sh
python tools/android_signing_setup.py \
  --keystore /secure/are-softwaregpu-release.jks \
  --create --configure-github
```

The script prompts for passwords, creates one RSA-3072 key with a 10,000-day
certificate, verifies access to both its certificate and private key, and sends
secret values to `gh secret set` through stdin. It prints only the public
certificate SHA-256 and secret names. It refuses to overwrite an existing key or
store one inside the repository. Uploading secrets is an owner operation; the
release does not generate a new production key automatically.

Back up the keystore, alias and passwords securely. To configure an existing key,
omit `--create`:

```sh
python tools/android_signing_setup.py \
  --keystore /secure/are-softwaregpu-release.jks --configure-github
```

For a local key check without uploading, omit `--configure-github` as well.
Successful secret-name readback is configuration evidence; the subsequent signed
APK and emulator execution establish runtime evidence.

## Retry and updates

Missing configuration produces `BLOCKED_MISSING_ANDROID_SIGNING_SECRETS` and a
failed Android publishing job. The published Windows/Linux installers remain
available. Node/npm publication has its own job and proceeds independently.

After configuration, retry the published desktop tag using Actions → **Android
companion release** → **Run workflow**, select `main`, and enter the real release
tag. The equivalent CLI command is:

```sh
gh workflow run android-gradio-apk-release.yml \
  --repo OuroborosCollective/ARE-SOFTWAREGPU-ENGINE \
  --ref main -f tag=v1.2.50
```

Replace the example tag with the already published release. A missing or moved
tag, unsuccessful publisher, unpublished desktop evidence or non-main source is
rejected. Existing APK bytes are downloaded and reverified on retries; an upload
never overwrites a different asset. Android and Node publishing each serialize
retries for the same tag, while distinct merge versions remain independent.

The visible Android `versionName` is `X.Y.Z`. Its integer `versionCode` is
`X * 10,000,000 + Y * 100,000 + Z`, with `X <= 209`, `Y <= 99`, `Z <= 99,999`
and a strictly positive result. These explicit bounds preserve ordering and
uniqueness; exceeding them fails the build instead of silently wrapping digits.
The version and source SHA are embedded in `assets/are-release.json` inside the
signed APK and checked again after building.

Keep the signing key unchanged. The publisher downloads the previous production
companion APK, verifies its actual certificate, and rejects accidental key
changes even if an earlier upload stopped before writing its receipt. The
historical SHA preview APKs used runner debug keys; switching from
one of those to the first permanent-key release requires uninstalling the old
preview first, which removes its saved endpoint settings. Later releases with
the same certificate and a higher versionCode can update in place.

The GitHub APK is a direct installation download. Google Play registration and
physical-device compatibility are separate work; the release evidence here is a
real Android API-35 emulator execution of the companion welcome screen. It does
not claim a remote test server was contacted or a native renderer ran on Android.

## Node companion contract

The same workflow also publishes the existing Node 20+ HTTPS client under the
shared version to GitHub Packages and attaches its npm tarball plus portable
Linux/Windows ZIPs to the same GitHub Release. These ZIPs require an installed
Node runtime. Its independent job verifies the downloaded registry tarball's
full SHA-256; an existing version with different bytes fails. `node-release.json`
and `node-checksums.sha256` bind the release assets to the source commit.

## Primary references

- [Android versionCode and versionName](https://developer.android.com/studio/publish/versioning)
- [Android update identity, certificate and version requirements](https://developer.android.com/google/play/app-updates)
- [Android app signing and key lifetime](https://developer.android.com/studio/publish/app-signing)
- [apksigner signing, verification and environment password inputs](https://developer.android.com/tools/apksigner)
- [Android emulator command-line execution](https://developer.android.com/studio/run/emulator-commandline)
