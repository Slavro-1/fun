"""Exercise installer upgrades and the command-line watcher in private temp dirs."""
import os
import select
from pathlib import Path
import json
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def script(path, body):
    path.write_text('#!/bin/sh\n' + body + '\n')
    path.chmod(0o755)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bin = self.root / 'commands'
        self.bin.mkdir()
        self.env = dict(HOME=str(self.root), PATH=f'{self.bin}:/usr/bin:/bin',
                        XDG_RUNTIME_DIR=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_CACHE_HOME=str(self.root / 'cache'), XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_SESSION_TYPE='x11', XDG_SESSION_ID='3', DISPLAY=':777')
        self.cfg = self.root / 'config/fun/settings.toml'
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text('idle_minutes = 5\ncharging_only = false\n')

    def run_ok(self, *args):
        r = subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_upgrade_install_again_and_uninstall(self):
        src = self.root / 'src'
        src.mkdir()
        prefix = str(self.root / 'stage')
        for name in ('install.sh', 'uninstall.sh', 'fun-idle', 'fun-config', 'fun'):
            shutil.copy2(ROOT / name, src)
        for name in ('fun_app', 'installer'):
            shutil.copytree(ROOT / name, src / name, ignore=shutil.ignore_patterns('__pycache__'))
        # Package prompting and the full renderer self-test have independent checks.
        (src / 'installer/dependencies.sh').write_text('installer_distro() { :; }; check_dependencies() { :; }')
        helper = (ROOT / 'installer/install_files.py').read_text().replace('/usr/local', prefix)
        (src / 'installer/install_files.py').write_text(helper)
        (src / 'extras.py').write_text('print("fixture scene check passed")')
        script(self.bin / 'sudo', '[ "$1" = /usr/bin/python3 ] || exit 99; exec "$@"')
        script(self.bin / 'systemctl', 'exit 1')
        legacy = self.root / '.config/autostart/fun-idle.desktop'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('[Desktop Entry]\nType=Application\nName=fun idle screensaver\n'
                          'Comment=Start the fun terminal screensavers using saved idle settings\n'
                          f'Exec={prefix}/bin/fun-idle\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
        entry = self.root / 'config/autostart/fun-idle.desktop'
        settings = self.cfg.read_bytes()
        self.run_ok(src / 'install.sh')
        self.assertFalse(legacy.exists())
        self.assertIn(f'Exec={prefix}/bin/fun-idle --autostart', entry.read_text())
        stamp = entry.stat().st_mtime_ns
        self.run_ok(src / 'install.sh')
        self.assertEqual(entry.stat().st_mtime_ns, stamp)
        self.assertEqual(list(entry.parent.glob('*.desktop')), [entry])
        self.assertIn('Configured delay 5 min', self.run_ok(prefix + '/bin/fun-idle', '--help'))
        self.run_ok(src / 'uninstall.sh')
        self.assertFalse(entry.exists())
        self.assertFalse(Path(prefix, 'bin/fun-idle').exists())
        self.assertFalse(Path(prefix, 'lib/fun/fun_wayland.py').exists())
        self.assertFalse(Path(prefix, 'lib/fun/fun_app/scenes/registry.py').exists())
        self.assertEqual(self.cfg.read_bytes(), settings)

    def test_manual_window_singleton_and_watcher_death(self):
        # A sudden parent death cannot run Python finally blocks.
        script(self.bin / 'terminal', 'echo "$$" > "$HOME/terminal.pid"; exec sleep 120')
        script(self.bin / 'loginctl', 'exit 1')
        self.env['FUN_TERMINAL'] = 'terminal'
        cli = str(ROOT / 'fun-idle')
        with subprocess.Popen([cli, '--now'], env=self.env) as watcher:
            try:
                pidfile = self.root / 'terminal.pid'
                deadline = time.monotonic() + 4
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                pid = int(pidfile.read_text())
                duplicate = subprocess.run([cli, '--now'], env=self.env, capture_output=True, timeout=3)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn(b'another fun-idle terminal', duplicate.stderr)
                # A pidfd becomes readable on exit, including before reaping.
                # Reading /proc/<pid>/stat races with the process disappearing.
                fd = os.pidfd_open(pid)
                try:
                    watcher.kill()
                    watcher.wait(timeout=2)
                    self.assertTrue(select.select([fd], [], [], 2)[0])
                finally:
                    os.close(fd)
            finally:
                if watcher.poll() is None:
                    watcher.terminate()

    def test_live_cli_test_then_normal_delay_and_no_duplicate(self):
        script(self.bin / 'loginctl', '''cat <<EOF
Id=3
User=$(id -u)
Type=x11
Class=user
Remote=no
Active=yes
State=active
LockedHint=no
EOF''')
        script(self.bin / 'busctl', """echo '{"type":"a(ssssuu)","data":[[]]}'""")
        script(self.bin / 'terminal', 'echo "$$" > "$HOME/terminal.pid"; exec sleep 120')
        script(self.bin / 'systemctl', 'exit 1')
        activity = self.root / 'last-input'
        activity.touch()
        counter = self.bin / 'xprintidle'
        counter.write_text('#!/usr/bin/python3\nimport os,time\n'
                           'print((time.time_ns() - os.stat(os.environ["INPUT"]).st_mtime_ns) // 1000000)\n')
        counter.chmod(0o755)
        self.env.update(INPUT=str(activity), FUN_TERMINAL='terminal', XDG_CURRENT_DESKTOP='XFCE')
        cli = str(ROOT / 'fun-idle')
        settings = self.cfg.read_bytes()
        with subprocess.Popen([cli, '--autostart'], env=self.env) as watcher:
            try:
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    states = list(self.root.glob('fun-idle-*/state'))
                    if states and json.loads(states[0].read_text()).get('backend') == 'X11 xprintidle':
                        break
                    time.sleep(.05)
                self.assertIn('Watcher: running', self.run_ok(cli, '--status'))
                self.run_ok(cli, '--autostart')  # exits while the first watcher still owns its lock
                with subprocess.Popen([cli, '--test'], env=self.env, stdout=subprocess.PIPE, text=True) as test:
                    try:
                        test.stdout.readline()
                        activity.touch()
                        pidfile = self.root / 'terminal.pid'
                        deadline = time.monotonic() + 20
                        while not pidfile.exists() and time.monotonic() < deadline:
                            time.sleep(.05)
                        self.assertTrue(pidfile.exists())
                        pid = int(pidfile.read_text())
                        activity.touch()
                        output = test.communicate(timeout=5)[0]
                        self.assertEqual(test.returncode, 0, output)
                        self.assertIn('PASS:', output)
                        with self.assertRaises(ProcessLookupError):
                            os.kill(pid, 0)
                    finally:
                        if test.poll() is None:
                            test.terminate()
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    report = self.run_ok(cli, '--status')
                    if 'Active notification delay: 300' in report:
                        break
                self.assertIn('Active notification delay: 300', report)
                self.assertEqual(settings, self.cfg.read_bytes())
            finally:
                watcher.send_signal(signal.SIGTERM)
                watcher.wait(timeout=6)


if __name__ == '__main__':
    unittest.main()
