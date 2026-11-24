#!/usr/bin/env bash
# Remove files installed by install.sh; keep saved settings, cache, and backups.
set -euo pipefail
# Transient services have no enablement symlinks. Stop this user's instances.
if command -v systemctl >/dev/null; then
  systemctl --user stop 'fun-idle-*.service' 2>/dev/null || true
fi
for file in /usr/local/bin/fun /usr/local/bin/fun-idle /usr/local/bin/fun-config \
            /usr/local/lib/fun/extras.py /usr/local/lib/fun/fun_settings.py /usr/local/lib/fun/snap.py /usr/local/lib/fun/{fun_wayland,fun_runtime,fun_session}.py; do
  if [ -e "$file" ]; then sudo rm -- "$file"; fi
done
# Keep /usr/local/lib/fun when it contains backups or other files.
sudo rmdir /usr/local/lib/fun 2>/dev/null || true
for file in "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/fun-idle.desktop" "$HOME/.config/autostart/fun-idle.desktop" \
            "${XDG_DATA_HOME:-$HOME/.local/share}/applications/fun-config.desktop" "$HOME/.local/share/applications/fun-config.desktop"; do
  if [ -f "$file" ] && grep -Eq '^Exec=/usr/local/bin/(fun-idle( --autostart)?|fun-config)$' "$file"; then
    rm -- "$file"
  fi
done
printf 'fun program files removed. Settings, cache, and backups were kept.\n'
