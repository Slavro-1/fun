"""Run the same acceptance checks in each laptop's actual KDE session."""
import contextlib
import hashlib
import json
import os
import pty
import select
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PY = '/usr/bin/python3'
BIN = Path('/usr/local/bin')
LIB = Path('/usr/local/lib/fun')
if os.getuid() == 0 or os.getuid() != os.geteuid():
    raise SystemExit('FAIL desktop verification requires a normal user')
sys.path.insert(0, str(ROOT))
from installer import install_files
from fun_app.idle import session as fun_session
from fun_app.idle.runtime import Runtime


def require(ok, message):
    if not ok:
        raise ValueError(message)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def policy_snapshot(kind):
    config = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')
    paths = [config / n for n in ('kscreenlockerrc', 'powermanagementprofilesrc', 'powerdevilrc',
                                  'fun/settings.toml', 'systemd/user/ac-screen-lock.service',
                                  'systemd/user/graphical-session.target.wants/ac-screen-lock.service')]
    paths += [Path('/etc/systemd/logind.conf')]
    for root in ('/etc/systemd', '/usr/lib/systemd', '/run/systemd'):
        paths += sorted((Path(root) / 'logind.conf.d').glob('*.conf'))
    state = {}
    for path in paths:
        try:
            state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            state[str(path)] = None
    if kind == 'x11':
        query = output('xset', 'q')
        require('Screen Saver:' in query and 'timeout:' in query, 'Cannot read X11 screensaver policy')
        state['X11'] = tuple(line.strip() for line in query.splitlines() if re.search(
            r'prefer blanking:|timeout:|Standby:|DPMS is |does not have the DPMS', line))
    return state


def session_check(kind):
    distro = {'x11': 'pop', 'wayland': 'debian'}[kind]
    import platform
    require(platform.freedesktop_os_release().get('ID') == distro, 'Unexpected distribution')
    require(fun_session.session_type() == kind and 'KDE' in os.getenv('XDG_CURRENT_DESKTOP', '').split(':'),
            f'Expected KDE {kind}')
    sid = fun_session.resolve_session()
    require(sid and fun_session.properties(sid).get('Active') == 'yes', 'Ambiguous or inactive graphical login')
    require(not os.environ.get('PYTHONOPTIMIZE'), 'Test assertions disabled')
    require(not any(os.getenv(k) for k in ('FUN_IDLE_FILE', 'FUN_IDLE_NO_LID', 'FUN_IDLE_NO_AC', 'FUN_BIN')),
            'Desktop has test or power overrides')


def suite():
    for script in ('fun', 'install.sh', 'uninstall.sh', 'installer/dependencies.sh', 'fun_app/legacy_savers.sh', 'scripts/final-prepush.sh'):
        run('/bin/bash', '-n', script)
    run('/bin/dash', '-n', 'scripts/final-prepush.sh')
    for path in [ROOT / 'extras.py', ROOT / 'fun-config', ROOT / 'fun-idle',
                 *(path for name in ('fun_app', 'installer', 'scripts', 'tests', 'tools')
                   for path in (ROOT / name).rglob('*.py'))]:
        compile(path.read_bytes(), str(path), 'exec')
    tests = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), 'test_*.py')
    require(tests.countTestCases() > 0, 'No tests discovered')
    result = unittest.TextTestRunner().run(tests)
    require(result.wasSuccessful() and not result.skipped, f'Unit tests failed or skipped: {result.skipped}')
    names = output('./fun', '--list').splitlines()
    require(len(names) == len(set(names)) == 41, 'Expected 41 distinct active scenes')
    run('./fun', '--selftest')
    for transport, mode, extras in [('shm', 'all', ['--fallbacks']), ('zlib', 'crash', [])]:
        run(PY, 'tools/rendering/ptygfx.py', 'extras.py', 'koi', '--jobs', '1',
            '--transport', transport, '--mode', mode, *extras)
    run(PY, 'tools/rendering/ptytest.py', 'extras.py', 'koi', 'resize')
    run(PY, 'tools/rendering/liveness.py', 'koi')


def installation():
    with contextlib.ExitStack() as stack:
        fs = install_files.Files(stack, False)
        for system in (False, True):
            _, manifest, targets, _ = install_files.layout(fs, system, True)
            if system:
                program_dirs = {path.parent for path in targets}
            owner = 0 if system else os.getuid()
            fs.directory(manifest.parent)  # reject linked parent directories
            info = manifest.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == owner and stat.S_IMODE(info.st_mode) == 0o600,
                    f'Unexpected manifest owner, mode or type: {manifest}')
            observed = {}
            stale = []
            for path, (data, mode) in targets.items():
                identity, _ = fs.inspect(path, limit=None)
                if data is None:
                    require(identity is None, f'Obsolete desktop entry {path}')
                elif identity and identity[2:] == [owner, stat.S_IFREG | mode, hashlib.sha256(data).hexdigest()]:
                    observed[str(path)] = identity
                else:
                    stale.append(str(path))
            require(not stale, 'Installation differs from the candidate: ' + ', '.join(stale))
            # Ask for the single privileged read only after all readable program
            # files match. Root never interprets project code or manifest data.
            raw = output('/usr/bin/sudo', '--', '/usr/bin/cat', '--', str(manifest)) if system else manifest.read_text()
            document = json.loads(raw)
            require(isinstance(document, dict) and document.get('format') == 'fun-install-1'
                    and document.get('files') == observed, f'Ownership manifest mismatch: {manifest}')
    for name in ('fun', 'fun-config', 'fun-idle'):
        require(shutil.which(name) == str(BIN / name), f'{name} shadows the installed entry point')
    config = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')
    for directory in [config / 'autostart', *(Path(d) / 'autostart' for d in
                      (os.getenv('XDG_CONFIG_DIRS') or '/etc/xdg').split(':'))]:
        for path in directory.glob('*.desktop'):
            if path != config / 'autostart/fun-idle.desktop':
                require(not re.search(r'(?m)^Exec=.*\b(?:fun-idle|fun-rotate)\b', path.read_text()),
                        f'Additional idle autostart {path}')
    for directory in sorted(program_dirs):
        require(not list(directory.glob('.fun-stage-*')), f'Unfinished transaction in {directory}')
    backups = [path for directory in program_dirs
               for path in directory.glob('fun*.bak*' if directory == BIN else '*.bak*')]
    print(f'Inspected {len(backups)} system backup paths. Installer rollback copies are retained.')
    if (BIN / 'fun-rotate').exists():
        print('Retained standalone legacy helper /usr/local/bin/fun-rotate (outside the installation manifest).')


def dependencies():
    run(PY, '-I', '-c', 'import tomllib, gi; gi.require_version("Gtk","4.0"); '
        'from gi.repository import Gtk; Gtk.ContentFit.CONTAIN')
    for name in ('loginctl', 'busctl', 'gdbus', 'systemctl', 'timeout', 'nice', 'shuf'):
        require(shutil.which(name), 'Missing dependency ' + name)
    if not shutil.which('kitty'):
        print('SKIPPED optional kitty binary; the watcher must verify its configured terminal')
    probe = subprocess.run([PY, '-I', '-c', 'from PIL import Image; Image.Resampling.NEAREST'])
    if probe.returncode:
        print('SKIPPED optional Pillow thumbnails (Pillow unavailable)')


def gui(binary):
    # A separate instance must never activate or close a pre-existing window.
    bus = ['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus',
           '--object-path', '/org/freedesktop/DBus', '--method']
    name = 'local.fun.Config'
    require(output(*bus, 'org.freedesktop.DBus.NameHasOwner', name) == '(false,)',
            'Close the existing fun settings window before GTK verification')
    with tempfile.TemporaryDirectory() as cache, subprocess.Popen(
            [binary], start_new_session=True, env=dict(os.environ, XDG_CACHE_HOME=cache)) as proc:
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and proc.poll() is None:
                probe = subprocess.run(['gdbus', 'introspect', '--session', '--dest', name,
                                        '--object-path', '/local/fun/Config/window/1'], capture_output=True)
                if probe.returncode == 0 and b'org.gtk.Actions' in probe.stdout:
                    owner = output(*bus, 'org.freedesktop.DBus.GetConnectionUnixProcessID', name)
                    require(owner == f'(uint32 {proc.pid},)', 'Another process owns the GTK window')
                    return
                time.sleep(.2)
            raise ValueError(f'GTK did not export a window: {binary}')
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise


def rotation():
    # Observe two different real renderer children in the launcher's own group.
    # Drain the PTY throughout so a full output buffer cannot stall rendering.
    master, slave = pty.openpty()
    names = []
    tail = b''
    try:
        with tempfile.TemporaryDirectory() as cache, subprocess.Popen(
                [BIN / 'fun', '--order', 'sequential', '--scenes', 'koi,silk'],
                stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                env=dict(os.environ, TERM='xterm-256color', FUN_SECONDS='5',
                         FUN_GFX='0', XDG_CACHE_HOME=cache)) as proc:
            try:
                deadline = time.monotonic() + 22
                while time.monotonic() < deadline and len(names) < 2 and proc.poll() is None:
                    if select.select([master], [], [], .15)[0]:
                        tail = (tail + os.read(master, 65536))[-8192:]
                    for pid in Path('/proc').glob('[0-9]*'):
                        try:
                            if os.getpgid(int(pid.name)) != proc.pid:
                                continue
                            args = (pid / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
                        except (ProcessLookupError, FileNotFoundError, PermissionError):
                            continue
                        if len(args) == 3 and args[1] == os.fsencode(LIB / 'extras.py'):
                            name = os.fsdecode(args[2])
                            if not name.startswith('--') and name not in names:
                                names.append(name)
                require(names == ['koi', 'silk'], f'Installed rotation observed {names}')
                proc.terminate()
                deadline = time.monotonic() + 6
                while proc.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        tail = (tail + os.read(master, 65536))[-8192:]
                while select.select([master], [], [], 0)[0]:
                    tail = (tail + os.read(master, 65536))[-8192:]
                require(proc.poll() == 0 and b'\x1b[?1049l' in tail, 'Launcher failed terminal cleanup')
                try:
                    os.killpg(proc.pid, 0)
                except ProcessLookupError:
                    return
                raise ValueError('Launcher left a child running after SIGTERM')
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
    finally:
        os.close(master)
        os.close(slave)


def terminal_sweep(binary):
    # Frames go to a private controlling PTY. Capture just the launcher's
    # per-scene verdicts and require the full registry in its original order.
    with tempfile.TemporaryDirectory() as tmp:
        summary = Path(tmp) / 'verdicts'
        run('script', '--quiet', '--return', '--command', '"$FUN_TEST_BIN" --test 1 > "$FUN_TEST_REPORT"',
            '/dev/null', stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=180,
            env=dict(os.environ, FUN_TEST_BIN=str(binary), FUN_TEST_REPORT=str(summary),
                     TERM='xterm-256color', XDG_CACHE_HOME=tmp))
        passed = re.findall(rb'PASS  ([a-z0-9-]+)\n', summary.read_bytes())
        require([n.decode() for n in passed] == output(binary, '--list').splitlines(),
                'Incomplete interactive scene sweep')


def installed_behavior():
    require(output(BIN / 'fun', '--list') == output('./fun', '--list'), 'Installed scene inventory differs')
    run(BIN / 'fun', '--selftest')
    terminal_sweep(BIN / 'fun')
    rotation()
    gui(BIN / 'fun-config')
    # A login watcher can still have the previous Python modules in memory.
    kind = fun_session.session_type()
    display = os.environ['WAYLAND_DISPLAY' if kind == 'wayland' else 'DISPLAY']
    rt = Runtime(kind + '/' + display)
    pid = rt.holder('watcher')
    require(pid and pid.isdecimal(), 'Installed watcher must be running')
    proc = Path('/proc') / pid
    argv = (proc / 'cmdline').read_bytes().split(b'\0')
    require(os.fsencode(BIN / 'fun-idle') in argv and proc.stat().st_uid == os.getuid(),
            'The running watcher must be the installed entry point for this user')
    env = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
    require(not any(env.get(k) for k in (b'FUN_IDLE_FILE', b'FUN_BIN', b'FUN_IDLE_NO_LID', b'FUN_IDLE_NO_AC')),
            'Running watcher has a test or power override')
    boot = int(re.search(r'^btime (\d+)$', Path('/proc/stat').read_text(), re.M)[1])
    ticks = int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    started = boot + ticks / os.sysconf('SC_CLK_TCK')
    modules = [BIN / 'fun-idle', LIB / 'fun_app/settings.py', LIB / 'fun_app/paths.py',
               *(LIB / 'fun_app/idle').glob('*.py')]
    require(all(p.stat().st_ctime < started for p in modules), 'Log in again to load the installed watcher')
    run(BIN / 'fun-idle', '--diagnose')
    run(BIN / 'fun-idle', '--status')
    print('Leave this desktop idle; move its pointer once the fullscreen saver appears.', flush=True)
    run(BIN / 'fun-idle', '--test', timeout=145)
    answer = input('Did one fullscreen saver appear and dismiss on physical input? Type OBSERVED: ')
    require(answer == 'OBSERVED', 'Visible idle/resume was not confirmed')


def main(kind):
    session_check(kind)
    before = policy_snapshot(kind)
    os.chdir(ROOT)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        for name, check in [('dependencies', dependencies), ('source suite, scenes and renderers', suite),
                            ('candidate GTK controls', lambda: run(PY, '-I', 'tests/gui_smoke.py', timeout=30)),
                            ('installation, autostart and obsolete artifacts', installation),
                            ('installed entry points and idle/resume', installed_behavior)]:
            print(f'Checking {kind} {name}', flush=True)
            check()
            print(f'PASS {kind} {name}', flush=True)
    finally:
        after = policy_snapshot(kind)
        changed = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
        require(not changed, f'Power, lock or saved settings changed: {changed}')
        print(f'PASS {kind} power, lock and saved settings comparison', flush=True)


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except (OSError, ValueError, KeyError, EOFError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        sys.exit(f'FAIL {exc}\nSKIPPED remaining desktop checks.')
