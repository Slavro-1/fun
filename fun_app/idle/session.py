"""Read-only session and idle policy queries. No graphical environment guessing."""
import json
import os
import subprocess
import time


def output(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=2,
                              check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def session_type():
    return os.getenv('XDG_SESSION_TYPE') or ('wayland' if os.getenv('WAYLAND_DISPLAY')
                                             else 'x11' if os.getenv('DISPLAY') else 'unknown')


def properties(sid):
    fields = 'Id User Type Class Remote Active LockedHint State Seat Display VTNr IdleHint IdleSinceHintMonotonic'
    args = [arg for field in fields.split() for arg in ('-p', field)]
    result = output('loginctl', 'show-session', sid, *args)
    return dict(line.split('=', 1) for line in (result or '').splitlines() if '=' in line)


def resolve_session():
    def matches(p):
        return (p.get('Id') and p.get('User') == str(os.getuid()) and p.get('Type') == session_type()
                and p.get('Class') in ('user', 'user-early', 'user-light', 'user-early-light')
                and p.get('Remote') == 'no'
                and (not os.getenv('XDG_SEAT') or os.environ['XDG_SEAT'] == p.get('Seat'))
                and (not os.getenv('XDG_VTNR') or os.environ['XDG_VTNR'] == p.get('VTNr'))
                and (session_type() != 'x11' or not os.getenv('DISPLAY') or not p.get('Display')
                     or p['Display'] == os.getenv('DISPLAY', '').split('.')[0]))

    for sid in filter(None, (os.getenv('XDG_SESSION_ID'), 'self')):
        p = properties(sid)
        if matches(p):
            return p['Id']
    # A user-manager process often has no "self". Never take the first seat
    # or the display manager's greeter in an ambiguous multi-session login.
    ids = output('loginctl', 'show-user', str(os.getuid()), '-p', 'Sessions', '--value')
    candidates = [sid for sid in (ids or '').split() if matches(properties(sid))]
    return candidates[0] if len(candidates) == 1 else None


def recover_login_display():
    """A user manager can finish importing the desktop environment after XDG startup."""
    kind = session_type()
    key = {'wayland': 'WAYLAND_DISPLAY', 'x11': 'DISPLAY'}.get(kind)
    if not key or os.getenv(key):
        return
    sid = resolve_session()
    if not sid:
        return
    # A user manager is shared between logins. Only accept a display exported
    # for the exact local graphical login we identified.
    for delay in (0, 1, 3, 6):
        time.sleep(delay)
        raw = output('systemctl', '--user', 'show-environment')
        env = dict(line.split('=', 1) for line in (raw or '').splitlines() if '=' in line)
        if env.get('XDG_SESSION_ID') == sid and env.get('XDG_SESSION_TYPE') == kind and env.get(key):
            for name in (key, 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS'):
                if env.get(name) and not os.getenv(name):
                    os.environ[name] = env[name]
            return


def bus(scope, dest, path, interface, method, *args):
    reply = output('busctl', '--' + scope, '--auto-start=no', '--json=short', 'call',
                   dest, path, interface, method, *args)
    if reply:
        try:
            return json.loads(reply)['data'][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
    return None


def system_inhibitors(rows):
    return [str(who).splitlines()[0][:80] if who else 'unnamed application'
            for what, who, why, mode, uid, pid in rows
            if 'idle' in what.split(':') and mode in ('block', 'block-weak')]


def kde_inhibition_detail(interface, path):
    # The modern property associates logind-style policy types with each row.
    value = bus('user', interface, path, 'org.freedesktop.DBus.Properties',
                'Get', 'ss', interface, 'ActiveInhibitions')
    typed = isinstance(value, dict) and isinstance(value.get('data'), list)
    if typed:
        rows = [row[1:3] for row in value['data']
                if isinstance(row, list) and len(row) >= 3 and isinstance(row[0], str)
                and 'idle' in row[0].split(':')]
    else:
        # Older versions list all active requests without per-request policy.
        rows = bus('user', interface, path, interface, 'ListInhibitions')
        if isinstance(rows, dict):
            rows = list(rows.items())
    labels = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, (tuple, list)) and len(row) == 2 and all(isinstance(s, str) for s in row):
            # Labels are provided by applications and can reach a terminal/log.
            fields = [''.join(c for c in s if c.isprintable())[:120] for s in row]
            labels.append(' — '.join(filter(None, fields)))
    if not labels:
        return ''
    prefix = 'screen requests' if typed else 'active requests, all types'
    return ' (' + prefix + ': ' + ', '.join(labels[:8]) + ')'


def blockers(session):
    reasons = []
    if session.get('Active') != 'yes' or session.get('LockedHint') != 'no' or session.get('State') != 'active':
        reasons.append('session locked, inactive or unidentified (check loginctl)')
    rows = bus('system', 'org.freedesktop.login1', '/org/freedesktop/login1',
               'org.freedesktop.login1.Manager', 'ListInhibitors')
    if rows is None:
        reasons.append('cannot read logind inhibitors (check busctl and the system bus)')
    else:
        reasons.extend(system_inhibitors(rows))
    desktop = os.getenv('XDG_CURRENT_DESKTOP', '').upper().split(':')
    if 'KDE' in desktop:
        interface = 'org.kde.Solid.PowerManagement.PolicyAgent'
        path = '/org/kde/Solid/PowerManagement/PolicyAgent'
        policy = bus('user', interface, path, interface, 'HasInhibition', 'u', '4')
        if policy is True:
            reasons.append('KDE PowerDevil screen inhibition' + kde_inhibition_detail(interface, path))
        elif policy is not False:
            reasons.append('cannot check KDE PowerDevil')
    if 'GNOME' in desktop:
        policy = bus('user', 'org.gnome.SessionManager', '/org/gnome/SessionManager',
                     'org.gnome.SessionManager', 'IsInhibited', 'u', '8')
        if policy:
            dest = 'org.gnome.SessionManager'
            paths = bus('user', dest, '/org/gnome/SessionManager', dest, 'GetInhibitors') or []
            apps = []
            for path in paths:
                iface = dest + '.Inhibitor'
                if (bus('user', dest, path, iface, 'GetFlags') or 0) & 8:
                    apps.append(bus('user', dest, path, iface, 'GetAppId') or 'unnamed')
            reasons.append('GNOME session idle inhibition' + (' (' + ', '.join(apps) + ')' if apps else ''))
        elif policy is None:
            reasons.append('cannot check GNOME session inhibitors')
    if 'GNOME' in desktop or 'KDE' in desktop:
        name = 'org.gnome.ScreenSaver' if 'GNOME' in desktop else 'org.freedesktop.ScreenSaver'
        path = '/org/gnome/ScreenSaver' if 'GNOME' in desktop else '/ScreenSaver'
        locked = bus('user', name, path, name, 'GetActive')
        if locked is True:
            reasons.append('desktop screen locker active')
        elif locked is not False:
            reasons.append('cannot check desktop screen locker')
    return reasons


class Hint:
    """A session manager supplies hints on its own schedule, sometimes never."""
    name = 'systemd-logind IdleHint'

    def __init__(self, sid):
        self.sid = sid
        self.edges = set()
        self.previous = None
        self.sampled_at = None
        self.seconds = 0
        self.sample()

    def sample(self):
        p = properties(self.sid)
        hint = p.get('IdleHint')
        if hint not in ('yes', 'no'):
            raise OSError('session has no IdleHint')
        stamp = int(p.get('IdleSinceHintMonotonic') or 0) / 1e6
        now = time.monotonic()
        if self.previous is not None and self.previous != hint:
            if self.sampled_at <= stamp <= now:
                self.edges.add(hint)
            else:
                self.edges.clear()  # stale timestamp accompanying a changed hint
        self.sampled_at = now
        resumed = self.previous == 'yes' and hint == 'no'
        self.previous = hint
        self.seconds = now - stamp if hint == 'yes' and len(self.edges) == 2 and 0 < stamp <= now else 0
        return resumed

    def pump(self, timeout):
        time.sleep(timeout)
        return self.sample()

    def idle(self):
        return self.seconds

    @property
    def evidence(self):
        return ('both hint transitions observed; conservative time since idle hint'
                if len(self.edges) == 2 else
                f'unverified (IdleHint={self.previous}); waiting for both idle and active hints; launch withheld')

    def close(self):
        pass
