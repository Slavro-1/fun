#!/usr/bin/env bash
# Installs the fun launcher, renderer, idle watcher, and GTK settings app.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON=/usr/bin/python3
python_files=(extras.py fun-idle fun-config fun_settings.py fun_wayland.py fun_runtime.py fun_session.py tools/snap.py)
for file in "${python_files[@]}" fun tools/install-deps.sh; do
  if [[ ! -f "$HERE/$file" ]]; then
    printf 'Missing %s. Run the installer from a complete checkout or extracted ZIP.\n' "$HERE/$file" >&2
    exit 1
  fi
done

admin=()
if (( EUID != 0 )); then
  if ! command -v sudo >/dev/null; then
    printf 'sudo is required to copy fun into /usr/local. Ask your administrator to enable it.\n' >&2
    exit 1
  fi
  admin=(sudo)
  printf '%s\n' 'sudo is used for package commands you approve and for copying fun into /usr/local.' \
    'It may ask for your password.'
elif [[ -n "${SUDO_USER:-}" ]]; then
  printf 'Run ./install.sh as your desktop user so login and menu entries are created for you.\n' >&2
  exit 1
fi

source "$HERE/tools/install-deps.sh"
check_dependencies "$PYTHON" "$(installer_distro /etc/os-release /usr/lib/os-release)" "${admin[@]}"

printf '\nChecking the source files and built-in scenes...\n'
if ! "$PYTHON" -I -c '
import sys
from pathlib import Path
for name in sys.argv[1:]:
    source = Path(name)
    compile(source.read_bytes(), str(source), "exec")
' "${python_files[@]/#/$HERE/}" || ! bash -n "$HERE/fun"; then
  printf 'Source validation failed. No fun files were copied.\n' >&2
  exit 1
fi

if ! selftest_output=$("$PYTHON" -I "$HERE/extras.py" --selftest); then
  printf '%s\n' "$selftest_output" 'Scene self-test failed. No fun files were copied.' >&2
  exit 1
fi
printf '%s\n' "$selftest_output" | tail -3

printf '\nInstalling program files in /usr/local...\n'
trap 'printf "Installation stopped while writing files. Resolve the error above and rerun ./install.sh.\n" >&2' ERR
stamp=$(date +%Y%m%d-%H%M%S-%N)
backed_up=false
for dir in /usr/local/lib/fun /usr/local/bin; do
  if [[ ! -d "$dir" ]]; then "${admin[@]}" install -d "$dir"; fi
done
for file in /usr/local/lib/fun/extras.py /usr/local/lib/fun/fun_settings.py /usr/local/lib/fun/snap.py /usr/local/lib/fun/{fun_wayland,fun_runtime,fun_session}.py /usr/local/bin/fun /usr/local/bin/fun-idle /usr/local/bin/fun-config; do
  if [[ -f "$file" || -L "$file" ]]; then
    "${admin[@]}" cp -a -- "$file" "$file.bak-$stamp"
    backed_up=true
  fi
done
"${admin[@]}" install -m 755 "$HERE/extras.py" /usr/local/lib/fun/extras.py
"${admin[@]}" install -m 644 "$HERE/fun_settings.py" /usr/local/lib/fun/fun_settings.py
for module in fun_wayland.py fun_session.py fun_runtime.py; do
  "${admin[@]}" install -m 644 "$HERE/$module" "/usr/local/lib/fun/$module"
done
"${admin[@]}" install -m 644 "$HERE/tools/snap.py" /usr/local/lib/fun/snap.py
"${admin[@]}" install -m 755 "$HERE/fun"       /usr/local/bin/fun
"${admin[@]}" install -m 755 "$HERE/fun-idle"  /usr/local/bin/fun-idle
"${admin[@]}" install -m 755 "$HERE/fun-config" /usr/local/bin/fun-config
if $backed_up; then
  printf 'Previous program files were saved alongside the new files with suffix .bak-%s.\n' "$stamp"
fi

autodir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
appdir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$autodir" "$appdir"
create_desktop_entry() {
  local file=$1 temp
  if [[ -e "$file" || -L "$file" ]]; then return 0; fi
  temp=$(mktemp "${file%/*}/.fun-entry.XXXXXXXX") || return 1
  if ! cat > "$temp" || ! mv -nT -- "$temp" "$file"; then
    rm -f -- "$temp"
    return 1
  fi
  rm -f -- "$temp"
}

entry="$autodir/fun-idle.desktop"
legacy="$HOME/.config/autostart/fun-idle.desktop"
is_fun_entry() {
  [[ -f "$1" && ! -L "$1" ]] && grep -Eq '^Exec=/usr/local/bin/fun-idle( --autostart)?$' "$1"
}
if [[ -e "$entry" || -L "$entry" ]] && ! is_fun_entry "$entry"; then
  printf 'Cannot replace a custom startup file at %s. Existing file preserved.\n' "$entry" >&2
  exit 1
fi
temp=$(mktemp "$autodir/.fun-entry.XXXXXXXX")
trap 'rm -f -- "$temp"' EXIT
cat > "$temp" <<'DESK'
[Desktop Entry]
Type=Application
Name=fun idle screensaver
Comment=Start the fun terminal screensavers using saved idle settings
Exec=/usr/local/bin/fun-idle --autostart
TryExec=/usr/local/bin/fun-idle
Terminal=false
NoDisplay=true
DESK
if ! cmp -s "$entry" "$temp"; then mv -T -- "$temp" "$entry"; fi
if [[ "$legacy" != "$entry" && ! "$legacy" -ef "$entry" ]] && is_fun_entry "$legacy"; then
  rm -- "$legacy"
fi
grep -Fxq 'Exec=/usr/local/bin/fun-idle --autostart' "$entry"
test -x /usr/local/bin/fun-idle
create_desktop_entry "$appdir/fun-config.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=fun settings
Comment=Configure terminal screensavers
Exec=/usr/local/bin/fun-config
Icon=preferences-system
Categories=Settings;Graphics;
Terminal=false
DESK

printf '\n%s\n' 'fun installed. Run fun to start and press Ctrl+C to exit.' \
  'Run fun-config from your graphical desktop to choose scenes and settings.' \
  'Log out and back in to load the updated watcher. It starts when idle activation is enabled.' \
  'Run fun-idle --diagnose to check idle detection for your session.'
