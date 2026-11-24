# Dependency preflight for install.sh. This file is sourced, not installed.

installer_distro() {
  local release_file ID=unknown
  for release_file in "$@"; do
    if [[ -r "$release_file" ]]; then
      source "$release_file"
      break
    fi
  done
  printf '%s\n' "$ID"
}

installer_package_manager() {
  case "$1" in
    debian|ubuntu|pop) printf 'apt\n' ;;
    fedora) printf 'dnf\n' ;;
    arch) printf 'pacman\n' ;;
    *) printf 'unsupported\n' ;;
  esac
}

PYTHON_CHECK='import sys, tomllib; sys.exit(sys.version_info < (3, 11))'
# Keep the imports in sync with fun-config and tools/snap.py.
GTK_CHECK='import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); from gi.repository import Gdk, GLib, Gtk; Gtk.ContentFit.CONTAIN'
PILLOW_CHECK='from PIL import Image, ImageDraw, ImageFont; Image.Resampling.NEAREST'

installer_python_ready() {
  "$1" -c "$PYTHON_CHECK" >/dev/null 2>&1
}

offer_packages() {
  local reason=$1 answer= status
  shift
  printf '\n%s\n  ' "$reason"
  printf '%q ' "$@"
  printf '\nRun this package installation command? [y/N] '
  if ! IFS= read -r answer || [[ ! ${answer,,} =~ ^(y|yes)$ ]]; then
    printf 'Permission not granted. Package command skipped.\n'
    return 1
  fi
  if "$@"; then
    return 0
  else
    status=$?
    printf 'Package command failed (exit %s). Check its output above.\n' "$status" >&2
    return 1
  fi
}

manual_dependencies() {
  local python=$1
  shift
  if (( $# )); then
    printf 'Ask your system administrator to make these distro packages available: %s\n' "$*"
  fi
  printf '%s\n' 'Use your distribution’s package manager to install system Python 3.11 or newer,' \
    'the PyGObject bindings for that Python, and GTK 4.8 or newer (Gtk and Gdk 4.0 typelibs).' \
    'To check the required dependencies, run:'
  printf "  %q -c '%s'\n" "$python" "$PYTHON_CHECK" "$python" "$GTK_CHECK"
  printf '%s\n' 'For thumbnails, install Pillow for the same system Python. For kitty graphics, install kitty.' \
    'Rerun ./install.sh when the required checks pass.'
}

check_dependencies() {
  local python=$1 distro=$2 manager python_package pillow_package
  shift 2
  local -a admin=("$@") gtk_packages=() install_command=() required=()
  local automatic=false python_state=missing gtk_state='not checked' pillow_state='not checked' kitty_state=missing
  manager=$(installer_package_manager "$distro")
  case "$manager" in
    apt)
      install_command=("${admin[@]}" apt install)
      python_package=python3
      gtk_packages=(python3-gi gir1.2-gtk-4.0)
      pillow_package=python3-pil
      ;;
    dnf)
      install_command=("${admin[@]}" dnf install)
      python_package=python3
      gtk_packages=(python3-gobject gtk4)
      pillow_package=python3-pillow
      ;;
    pacman)
      install_command=("${admin[@]}" pacman -S --needed)
      python_package=python
      gtk_packages=(python-gobject gtk4)
      pillow_package=python-pillow
      ;;
  esac

  if [[ "$manager" == unsupported ]]; then
    printf 'Automatic package installation is unavailable for distro ID %s.\n' "$distro"
  elif command -v "$manager" >/dev/null; then
    automatic=true
    printf 'Package manager: %s (%s)\n' "$manager" "$distro"
  else
    printf 'Automatic package installation is unavailable because %s was not found.\n' "$manager"
  fi

  if installer_python_ready "$python"; then
    python_state=present
    gtk_state=missing
    pillow_state=missing
    if "$python" -c "$GTK_CHECK" >/dev/null 2>&1; then gtk_state=present; fi
    if "$python" -c "$PILLOW_CHECK" >/dev/null 2>&1; then pillow_state=present; fi
  elif [[ -e "$python" ]]; then
    python_state='unusable (3.11+ required)'
  fi
  if command -v kitty >/dev/null; then kitty_state=present; fi

  printf '\nDependency check\n'
  printf '  Required     Python 3.11+ (%s): %s\n' "$python" "$python_state"
  printf '  Required     GTK 4.8+ / PyGObject (settings window): %s\n' "$gtk_state"
  printf '  Recommended  Pillow (scene thumbnails): %s\n' "$pillow_state"
  printf '  Recommended  kitty (terminal graphics and default idle terminal): %s\n' "$kitty_state"

  if [[ "$python_state" != missing && "$python_state" != present ]]; then
    printf '\nThe system Python must support Python 3.11 or newer. You may need a newer distro release.\n' >&2
    manual_dependencies "$python"
    printf 'Installation stopped before copying any fun files.\n' >&2
    return 1
  fi

  if [[ "$gtk_state" != present ]]; then
    if ! $automatic; then
      manual_dependencies "$python" ${python_package:+"$python_package"} "${gtk_packages[@]}"
      printf 'Installation stopped before copying any fun files.\n' >&2
      return 1
    fi
    if [[ "$python_state" == missing ]]; then required+=("$python_package"); fi
    required+=("${gtk_packages[@]}")
    if ! offer_packages 'Install required packages for the GUI-enabled setup.' \
      "${install_command[@]}" "${required[@]}"; then
      printf 'Installation stopped before copying any fun files. Required dependencies are still unverified.\n' >&2
      return 1
    fi
    if ! installer_python_ready "$python" || ! "$python" -c "$GTK_CHECK"; then
      printf 'The required Python or GTK4 import check still fails. No fun files were copied.\n' >&2
      manual_dependencies "$python"
      return 1
    fi
    printf 'Required Python and GTK4 imports passed.\n'
  fi

  if ! "$python" -c "$PILLOW_CHECK" >/dev/null 2>&1; then
    if $automatic; then
      offer_packages 'Install Pillow for scene thumbnails (optional).' \
        "${install_command[@]}" "$pillow_package" || true
    fi
    if ! "$python" -c "$PILLOW_CHECK" >/dev/null 2>&1; then
      printf 'Continuing without thumbnail generation. Install Pillow for %s to enable it later.\n' "$python"
    fi
  fi
  if ! command -v kitty >/dev/null; then
    if $automatic; then
      offer_packages 'Install kitty for terminal graphics (optional).' \
        "${install_command[@]}" kitty || true
    fi
    if ! command -v kitty >/dev/null; then
      printf '%s\n' 'Continuing with your current terminal. For automatic idle launch without kitty,' \
        'configure the FUN_TERMINAL override in your desktop session (see README).'
    fi
  fi
}
