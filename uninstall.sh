#!/usr/bin/env bash
# Remove files installed by install.sh; keep saved settings, cache, and backups.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -n "${SUDO_USER:-}" ]]; then
  echo 'Run ./uninstall.sh as your desktop user.' >&2
  exit 1
fi
/usr/bin/python3 -I "$HERE/tools/install_files.py" uninstall
# Transient services have no enablement symlinks. Stop this user's instances.
if command -v systemctl >/dev/null; then
  systemctl --user stop 'fun-idle-*.service' 2>/dev/null || true
fi
printf 'Uninstall complete. Settings, cache, and backups were kept.\n'
