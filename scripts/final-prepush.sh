#!/bin/dash -p
# Only OS executables run before the privilege drop. No shell startup files.
set -eu
fail() { echo "FAIL $*" >&2; exit 1; }
[ "$#" -eq 0 ] || fail 'Run without arguments.'
[ "$(/usr/bin/id -u)" = 0 ] || fail 'Run sudo ./scripts/final-prepush.sh from your desktop account.'
case ${SUDO_UID-} in ''|0|*[!0-9]*) fail 'A normal sudo caller is required.';; esac
[ -n "${SUDO_USER-}" ] && [ "$(/usr/bin/id -u -- "$SUDO_USER")" = "$SUDO_UID" ] ||
    fail 'Inconsistent sudo identity.'
IFS= read -r login_uid < /proc/self/loginuid || [ -n "${login_uid-}" ]
[ "$login_uid" = "$SUDO_UID" ] || fail 'The audit login UID does not match the sudo caller.'
# Resolve the adjacent helper only after sudo has switched to the caller.
exec /usr/bin/sudo -H -u "#$SUDO_UID" -- /usr/bin/env -i \
    PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 XDG_RUNTIME_DIR="/run/user/$SUDO_UID" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$SUDO_UID/bus" \
    /usr/bin/python3 -I "${0%/*}/prepush.py"
