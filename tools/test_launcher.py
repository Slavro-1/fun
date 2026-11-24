"""Run the launcher from a spaced path with private settings and mocked playback."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        src = self.home / 'project with spaces'
        src.mkdir()
        for name in ('fun', 'fun_settings.py'):
            shutil.copy2(ROOT / name, src)
        self.fun = src / 'fun'
        self.engine = src / 'extras.py'
        self.engine.write_text("""import os,sys,time
if sys.argv[1] == '--list':
    print('aurora\\nkoi\\nsilk')
else:
    print(sys.argv[1], file=open(os.environ['MARK'], 'w'), flush=True)
    time.sleep(60 if 'WAIT' in os.environ else 0)
    sys.exit(int(os.environ.get('EXIT_CODE', 0)))
""")
        self.path = self.home / 'bin'
        self.path.mkdir()
        self.log = self.home / 'played'
        self.power = self.home / 'power'
        self.mark = self.home / 'started'
        self.env = dict(HOME=str(self.home), PATH=f'{self.path}:/usr/bin:/bin',
                        DISPLAY=':777', TERM='xterm', PLAYED=str(self.log), POWER=str(self.power),
                        MARK=str(self.mark), FUN_ORDER='sequential')
        self.cfg = self.home / '.config/fun/settings.toml'
        self.cfg.parent.mkdir(parents=True)
        for name in ('gsettings', 'xset', 'systemd-inhibit', 'gnome-session-inhibit', 'kitty'):
            self.command(name, 'echo "$0" >> "$POWER"; exit 1')
        for name in ('cmatrix', 'sleep', 'clear', 'stty'):
            self.command(name, 'exit 0')
        self.command('timeout', '''/usr/bin/python3 -c 'import json,sys,os
with open(os.environ["PLAYED"],"a") as f: print(json.dumps(sys.argv[1:]),file=f)' "$@"
if [ -n "$WAIT" ]; then echo ready > "$MARK"; exec /bin/sleep 60; fi
exit 42''')

    def command(self, name, body):
        path = self.path / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def play(self, *args, env=None):
        self.log.unlink(missing_ok=True)
        result = subprocess.run([self.fun, *args], env=self.env | (env or {}),
                                capture_output=True, text=True, timeout=10)
        self.assertFalse(self.power.exists())
        return result, [json.loads(line)[7:] for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_exact_selection_and_whitespace(self):
        _, commands = self.play('--scenes', 'koi')
        self.assertEqual(commands, [['python3', str(self.engine), 'koi']])
        _, commands = self.play('--scenes', 'silk,koi,koi')
        self.assertEqual([cmd[-1] for cmd in commands], ['koi', 'silk'])

    def test_default_gui_and_cli_precedence(self):
        _, commands = self.play()
        self.assertEqual(commands[0][0], 'cmatrix')
        self.assertEqual([c[-1] for c in commands if c[:2] == ['python3', str(self.engine)]],
                         ['aurora', 'koi', 'silk'])
        self.cfg.write_text('scenes=["plexus","koi","synthwave"]\nquality=[]\nminutes=1.5\n')
        _, commands = self.play()
        self.assertEqual(commands, [['python3', str(self.engine), 'koi']])
        _, commands = self.play('--scenes', 'aurora', env={'FUN_SCENES': 'silk'})
        self.assertEqual(commands, [['python3', str(self.engine), 'aurora']])

    def test_random_and_invalid_selection(self):
        self.command('shuf', 'exec tac')
        _, commands = self.play('--order', 'random', '--scenes', 'aurora,silk')
        self.assertEqual([cmd[-1] for cmd in commands], ['silk', 'aurora'])
        for names in ('', 'ko', 'koi,absent', 'koi,', 'plexus', 'synthwave'):
            with self.subTest(names=names):
                result, commands = self.play('--scenes', names)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr)
                self.assertFalse(commands)

    def test_power_on_exit_child_failure_and_idle_launch(self):
        saved = self.home / '.cache/fun-power.saved'
        saved.parent.mkdir()
        saved.write_text('old settings')
        for overrides in ({}, {'FUN_NO_POWER': '1'}, {'FUN_IDLE_LAUNCH': '1'}):
            for code in ('0', '3'):
                result, _ = self.play('--scene', 'koi', env=overrides | {'EXIT_CODE': code})
                self.assertEqual(result.returncode, int(code))
                self.assertIn('\x1b[?25h', result.stdout)
            _, commands = self.play('--scenes', 'koi', env=overrides)
            self.assertEqual(len(commands), 1)
        self.assertEqual(saved.read_text(), 'old settings')

    def test_signals_restore_terminal(self):
        for args in (('--scene', 'koi'), ('--scenes', 'koi')):
            for sig in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(args=args, sig=sig):
                    self.mark.unlink(missing_ok=True)
                    with subprocess.Popen([self.fun, *args], env=self.env | {'WAIT': '1'},
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                        try:
                            deadline = time.monotonic() + 5
                            while not self.mark.exists() and time.monotonic() < deadline:
                                time.sleep(.02)
                            self.assertTrue(self.mark.exists())
                            proc.send_signal(sig)
                            out, _ = proc.communicate(timeout=4)
                            self.assertIn(b'\x1b[?1049l', out)
                        finally:
                            if proc.poll() is None:
                                proc.kill()
                    self.assertFalse(self.power.exists())
