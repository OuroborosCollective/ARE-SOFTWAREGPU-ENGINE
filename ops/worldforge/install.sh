#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(id -u)" = 0
test -d /opt/are-media
id unityarpg >/dev/null
install -d -m 0755 /usr/local/lib/are-worldforge
install -m 0644 update.py /usr/local/lib/are-worldforge/update.py
install -d -o unityarpg -g unityarpg -m 0700 /var/lib/unityarpg/.local/share/are-arpg/worldforge-are /var/lib/unityarpg/.local/state/are-softwaregpu
install -m 0644 are-worldforge-*.service are-worldforge-*.timer /etc/systemd/system/
cli=/usr/local/bin/are-worldforge
target=/opt/are-media/learning-current/venv/bin/are-worldforge
if [[ ! -e "$cli" && ! -L "$cli" ]]; then ln -s "$target" "$cli"; fi
test "$(readlink "$cli")" = "$target"
systemctl daemon-reload
systemctl enable --now are-worldforge-update.timer are-worldforge-review.timer
