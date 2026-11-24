#!/usr/bin/env bash
# Remove files installed by install.sh; keep saved settings, cache, and backups.
set -euo pipefail
for file in /usr/local/bin/fun /usr/local/bin/fun-idle /usr/local/bin/fun-config \
            /usr/local/lib/fun/extras.py /usr/local/lib/fun/fun_settings.py /usr/local/lib/fun/snap.py; do
  if [ -e "$file" ]; then sudo rm -- "$file"; fi
done
# Keep /usr/local/lib/fun when it contains backups or other files.
sudo rmdir /usr/local/lib/fun 2>/dev/null || true
for file in "$HOME/.config/autostart/fun-idle.desktop" "$HOME/.local/share/applications/fun-config.desktop"; do
  if [ -f "$file" ] && grep -Eq '^Exec=/usr/local/bin/(fun-idle|fun-config)$' "$file"; then
    rm -- "$file"
  fi
done
printf 'fun program files removed. Settings, cache, and backups were kept.\n'
