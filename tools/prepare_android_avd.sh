#!/usr/bin/env bash
# Configure one job-owned AVD location for both the Android SDK manager and emulator.
set -euo pipefail
export ANDROID_USER_HOME
ANDROID_USER_HOME=$(mktemp -d "${RUNNER_TEMP:?}/are-android-home-XXXXXXXX")
export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
mkdir -p "$ANDROID_AVD_HOME"
printf 'no\n' | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd \
  --name are_release --package 'system-images;android-35;google_apis;x86_64' \
  --device pixel_7 --path "$ANDROID_AVD_HOME/are_release.avd"
test -s "$ANDROID_AVD_HOME/are_release.ini"
"$ANDROID_HOME/emulator/emulator" -list-avds | grep -Fx are_release
printf 'ANDROID_USER_HOME=%s\nANDROID_AVD_HOME=%s\n' "$ANDROID_USER_HOME" "$ANDROID_AVD_HOME" >> "${GITHUB_ENV:?}"
