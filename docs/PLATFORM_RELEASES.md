# Versioned application releases

Owner: Thomas Markgraf, using the artist pseudonym **OuroborosCollective**.

## Release contract

Every successfully verified integration into `main` receives one immutable
`v1.2.N` release. `N` is the first-parent distance from the existing release
baseline `22c436385fad7bf79d074d9eaf2cce458a81810e`. Re-running a workflow for
the same integration keeps the same version. Wall-clock time, workflow run
numbers and the number of commits inside a pull request are not version inputs.

The Git tag, checkout, package version and artifact receipts must identify the
same source commit. An existing tag or asset with different content blocks
publication; published versions are not overwritten.

Windows and Linux are the first acceptance stage. Android and Firefox release
integration follows their actual installation, renderer and uninstallation
checks. A unit test of a package manifest is not a successful installation.

## Distribution surfaces

| Platform | Package | Execution and update boundary |
| --- | --- | --- |
| Windows x64 | Per-user EXE installer | Bundled Python CPU engine; installation and uninstallation exercised on Windows |
| Linux x86_64 | Executable `.run` installer | Bundled Python CPU engine in a versioned user directory; no `sudo` required |
| Android | Gradio companion APK | HTTPS client for a separately configured engine; release updates require one persistent signing identity |
| Firefox desktop | Diagnostics XPI and matching source ZIP | Local capability and pixel diagnostics; regular Firefox installation requires Mozilla signing |

The desktop packages run the Python/NumPy engine without a separate Python
installation. Compiler-dependent native research backends and external tools
such as FFmpeg are separate capabilities and must not be inferred from an
installer test. See the source-based [quick start](QUICKSTART.md) for those paths.

## Install and run

Download the package for the desired tag from
[GitHub Releases](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases).
Verify its SHA-256 against the release's `checksums.txt` before installing.

### Windows x64

Open `ARE-SoftwareGPU-X.Y.Z-windows-x64-setup.exe`. The default destination is
`%LOCALAPPDATA%\Programs\ARE-SoftwareGPU`. The Start menu entry
**ARE SoftwareGPU Console** opens a console with the installed command available:

```console
are-softwaregpu --version
are-softwaregpu --info
are-softwaregpu --blender
```

The last command executes the existing CPU rendering demo. The shortcut adjusts
only its own console's PATH. The same application ID supports later installer
versions. Uninstall through Windows Settings or the supplied Start menu entry.
The setup EXE is not Authenticode-signed; no Windows signing certificate is
configured by this change.

### Linux x86_64

Use the exact downloaded version in these filenames. The native CI build uses
Ubuntu 22.04; older glibc distributions and other CPU architectures are not
covered by that acceptance run.

```sh
chmod +x ARE-SoftwareGPU-X.Y.Z-linux-x86_64.run
./ARE-SoftwareGPU-X.Y.Z-linux-x86_64.run
"${XDG_DATA_HOME:-$HOME/.local/share}/ARE-SoftwareGPU/X.Y.Z/bin/are-softwaregpu" --version
"${XDG_DATA_HOME:-$HOME/.local/share}/ARE-SoftwareGPU/X.Y.Z/bin/are-softwaregpu" --blender
```

An absolute custom destination is accepted with `--prefix /absolute/path`.
Every version has its own default directory. Existing destinations are refused,
so a new installation does not overwrite an old version or unrelated files.
Remove a chosen installation with its `uninstall.sh`; files not listed in its
installation inventory are retained. No separate Python, pip or network access
is needed to install the downloaded package.

## Acceptance and publication

1. Run the existing CPU regression and installed-wheel matrices for the exact
   `main` commit.
2. Build both desktop packages on their native operating systems. Install each
   into a temporary directory, start the installed executable outside the source
   tree, compare an actual rendered frame with the source invocation, and
   uninstall. Keep the original logs, package hashes and source-bound receipt.
3. Publish the already tested installer bytes with the wheel, source distribution
   and checksums under the immutable version tag. Read back the published bytes.
4. Build the Android/Firefox packages for that same version. Signing credentials
   are consumed only by trusted publication jobs, never by pull-request code.
   Missing signing configuration is reported explicitly and is not replaced by
   an ephemeral debug identity or a claim of store approval.
5. Keep download publication, successful signing, store review and real-device
   acceptance as separate recorded outcomes.

Existing published versions remain available for rollback. A new installation
does not silently change the system graphics driver or the engine's simulation
contracts. The engine's PolyForm Noncommercial 1.0.0 license and Required Notice
are included in every application package.

## Upstream packaging contracts

- [PyInstaller usage and platform-specific builds](https://pyinstaller.org/en/stable/usage.html)
- [Inno Setup per-user installation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
- [Android signing and update identity](https://developer.android.com/studio/publish/app-signing)
- [Android version codes](https://developer.android.com/studio/publish/versioning)
- [Firefox web-ext signing commands](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/)
- [Firefox signing and distribution](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)

Build and release outcomes are recorded separately in the pull request and
[release status](RELEASE_STATUS.md); this contract alone is not runtime evidence.
