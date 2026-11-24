#!/usr/bin/env bash
# Installs the fun launcher, renderer, idle watcher, and GTK settings app.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON=/usr/bin/python3
python_files=(extras.py fun-idle fun-config fun_settings.py fun_wayland.py fun_runtime.py fun_session.py tools/snap.py tools/install_files.py)
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

"$PYTHON" -I "$HERE/tools/install_files.py" install
printf '\n%s\n' 'fun installed. Run fun to start and press Ctrl+C to exit.' \
  'Run fun-config from your graphical desktop to choose scenes and settings.' \
  'Log out and back in to load the updated watcher. It starts when idle activation is enabled.' \
  'Run fun-idle --diagnose to check idle detection for your session.'
