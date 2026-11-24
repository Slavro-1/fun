#!/usr/bin/env bash
# Installs the fun launcher, renderer, idle watcher, and GTK settings app.
# Run from the folder that contains: extras.py  fun  fun-idle  fun-config  install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"
for f in extras.py fun fun-idle fun-config fun_settings.py tools/snap.py; do [ -f "$HERE/$f" ] || { echo "missing $HERE/$f"; exit 1; }; done
command -v python3 >/dev/null || { echo "fun needs Python 3.11 or newer (python3 not found)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "fun needs Python 3.11 or newer." >&2; exit 1; }
command -v sudo >/dev/null || { echo "fun needs sudo to copy files into /usr/local." >&2; exit 1; }

echo "== syntax check"
python3 -I -m py_compile "$HERE/extras.py" "$HERE/fun-idle" "$HERE/fun-config" "$HERE/fun_settings.py" "$HERE/tools/snap.py"
bash -n "$HERE/fun"

echo "== workspace self-test of all scenes in both render modes"
python3 -I "$HERE/extras.py" --selftest | tail -3

echo "== backup + install"
sudo install -d /usr/local/lib/fun
for file in /usr/local/lib/fun/extras.py /usr/local/lib/fun/fun_settings.py /usr/local/lib/fun/snap.py /usr/local/bin/fun /usr/local/bin/fun-idle /usr/local/bin/fun-config; do
  [ ! -f "$file" ] || sudo cp -a "$file" "$file.bak-$TS"
done
sudo install -m 755 "$HERE/extras.py" /usr/local/lib/fun/extras.py
sudo install -m 644 "$HERE/fun_settings.py" /usr/local/lib/fun/fun_settings.py
sudo install -m 644 "$HERE/tools/snap.py" /usr/local/lib/fun/snap.py
sudo install -m 755 "$HERE/fun"       /usr/local/bin/fun
sudo install -m 755 "$HERE/fun-idle"  /usr/local/bin/fun-idle
sudo install -m 755 "$HERE/fun-config" /usr/local/bin/fun-config
echo "backups end in .bak-$TS"

echo "== autostart the idle watcher at login"
mkdir -p "$HOME/.config/autostart" "$HOME/.cache/fun"
[ ! -f "$HOME/.config/autostart/fun-idle.desktop" ] || cp -p "$HOME/.config/autostart/fun-idle.desktop" "$HOME/.config/autostart/fun-idle.desktop.bak-$TS"
cat > "$HOME/.config/autostart/fun-idle.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=fun idle screensaver
Comment=Start the fun terminal screensavers using saved idle settings
Exec=/usr/local/bin/fun-idle
X-GNOME-Autostart-enabled=true
NoDisplay=true
DESK
mkdir -p "$HOME/.local/share/applications"
[ ! -f "$HOME/.local/share/applications/fun-config.desktop" ] || cp -p "$HOME/.local/share/applications/fun-config.desktop" "$HOME/.local/share/applications/fun-config.desktop.bak-$TS"
cat > "$HOME/.local/share/applications/fun-config.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=fun settings
Comment=Configure terminal screensavers
Exec=/usr/local/bin/fun-config
Icon=preferences-system
Categories=Settings;Graphics;
Terminal=false
DESK

echo "Idle detection depends on your session and device permissions; check fun-idle --diagnose."
echo
echo "Installed! Run fun to start, or fun-config to choose scenes and settings."
echo "Press Ctrl+C to leave fun. Kitty graphics auto-detects support."
echo "For automatic idle screensavers, check fun-idle --diagnose."
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
  echo "Note: fun-config needs GTK4 and PyGObject; the terminal screensavers still work without them."
fi
