"""Test dependency preflight using only temporary files and fake package commands."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HELPER = Path(__file__).with_name('install-deps.sh').resolve()
PYTHON_WRAPPER = """#!/bin/bash
exec "$TEST_PYTHON" -S "$@"
"""
MANAGER_WRAPPER = """#!/bin/bash
exec "$TEST_PYTHON" "$FAKE_MANAGER" "${0##*/}" "$@"
"""
FAKE_MANAGER = '''import json
import os
from pathlib import Path
import shutil
import sys

state = Path(os.environ['TEST_STATE'])
with (state / 'commands').open('a') as log:
    print(json.dumps(sys.argv[1:]), file=log)
packages = sys.argv[2:]
if os.environ.get('FAIL_PACKAGE') in packages:
    sys.exit(42)
if os.environ.get('NO_INSTALL'):
    sys.exit(0)
if {'python3', 'python'}.intersection(packages):
    shutil.copy2(state / 'python-wrapper', state / 'system-python')
if {'python3-gi', 'python3-gobject', 'python-gobject'}.intersection(packages):
    (state / 'gi').touch()
if {'gir1.2-gtk-4.0', 'gtk4'}.intersection(packages):
    (state / 'gtk4').touch()
    (state / 'old-gtk').unlink(missing_ok=True)
if {'python3-pil', 'python3-pillow', 'python-pillow'}.intersection(packages):
    (state / 'pillow').touch()
if 'kitty' in packages:
    shutil.copy2(state / 'python-wrapper', state / 'bin' / 'kitty')
'''


class DependencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)
        self.bin = self.state / 'bin'
        self.bin.mkdir()
        self.python = self.state / 'system-python'
        self.release = self.state / 'os-release'
        self.fake_manager = self.state / 'manager.py'
        self.fake_manager.write_text(FAKE_MANAGER)
        self.write_executable(self.state / 'python-wrapper', PYTHON_WRAPPER)
        self.write_executable(self.python, PYTHON_WRAPPER)
        self.write_executable(self.bin / 'sudo', '#!/bin/bash\nexec "$@"\n')
        for manager in ('apt', 'dnf', 'pacman'):
            self.write_executable(self.bin / manager, MANAGER_WRAPPER)

        modules = self.state / 'modules'
        gi = modules / 'gi'
        pillow = modules / 'PIL'
        gi.mkdir(parents=True)
        pillow.mkdir()
        (gi / '__init__.py').write_text('''
import os
from pathlib import Path

state = Path(os.environ['TEST_STATE'])
if not (state / 'gi').exists():
    raise ImportError('PyGObject unavailable')

versions = {}

def require_version(namespace, version):
    versions[namespace] = version
''')
        (gi / 'repository.py').write_text('''
from types import SimpleNamespace
from gi import state, versions

if versions != {'Gtk': '4.0', 'Gdk': '4.0'} or not (state / 'gtk4').exists():
    raise ImportError('GTK 4 introspection unavailable')
Gtk = SimpleNamespace()
if not (state / 'old-gtk').exists():
    Gtk.ContentFit = SimpleNamespace(CONTAIN=1)
Gdk = GLib = object()
''')
        (pillow / '__init__.py').write_text('''
import os
from pathlib import Path
from types import SimpleNamespace

if not (Path(os.environ['TEST_STATE']) / 'pillow').exists():
    raise ImportError('Pillow unavailable')
Image = SimpleNamespace(Resampling=SimpleNamespace(NEAREST=0))
ImageDraw = ImageFont = object()
''')
        self.env = {
            'PATH': str(self.bin),
            'PYTHONPATH': str(modules),
            'PYTHONDONTWRITEBYTECODE': '1',
            'TEST_PYTHON': sys.executable,
            'TEST_STATE': str(self.state),
            'FAKE_MANAGER': str(self.fake_manager),
        }

    @staticmethod
    def write_executable(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def provide(self, *dependencies):
        for name in dependencies:
            (self.state / name).touch()

    def preflight(self, distro='debian', answers='', **env):
        self.release.write_text(f'ID="{distro}"\nID_LIKE=debian\n')
        return subprocess.run(
            ['/bin/bash', '-euo', 'pipefail', '-c',
             'source "$1"; check_dependencies "$2" "$(installer_distro "$3")" sudo',
             'preflight', str(HELPER), str(self.python), str(self.release)],
            input=answers, text=True, capture_output=True, env=self.env | env, timeout=10,
        )

    def commands(self):
        log = self.state / 'commands'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_distro_package_commands(self):
        apt = ('apt', ['install'], ['python3-gi', 'gir1.2-gtk-4.0'], 'python3-pil')
        distros = {
            'debian': apt, 'ubuntu': apt, 'pop': apt,
            'fedora': ('dnf', ['install'], ['python3-gobject', 'gtk4'], 'python3-pillow'),
            'arch': ('pacman', ['-S', '--needed'], ['python-gobject', 'gtk4'], 'python-pillow'),
        }
        for distro, (manager, flags, gtk, pillow) in distros.items():
            with self.subTest(distro=distro):
                for path in ('gi', 'gtk4', 'pillow', 'bin/kitty', 'commands'):
                    (self.state / path).unlink(missing_ok=True)
                result = self.preflight(distro, 'y\nyes\nY\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Package manager: {manager} ({distro})', result.stdout)
                self.assertIn('Required Python and GTK4 imports passed.', result.stdout)
                self.assertEqual(self.commands(), [
                    [manager, *flags, *gtk],
                    [manager, *flags, pillow],
                    [manager, *flags, 'kitty'],
                ])

    def test_present_dependencies_skip_all_package_commands(self):
        self.provide('gi', 'gtk4', 'pillow')
        self.write_executable(self.bin / 'kitty', '#!/bin/bash\nexit 0\n')
        result = self.preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count(': present'), 4)
        self.assertNotIn('Run this package installation command?', result.stdout)
        self.assertEqual(self.commands(), [])

    def test_refusing_required_packages_or_eof_stops(self):
        for answer in ('n\n', '\n', ''):
            with self.subTest(answer=answer):
                result = self.preflight(answers=answer)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Permission not granted', result.stdout)
                self.assertIn('before copying any fun files', result.stderr)
                self.assertIn('sudo apt install python3-gi gir1.2-gtk-4.0', result.stdout)
                self.assertEqual(self.commands(), [])

    def test_optional_packages_can_be_declined_independently(self):
        self.provide('gi', 'gtk4')
        result = self.preflight(answers='n\ny\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [['apt', 'install', 'kitty']])
        self.assertIn('Continuing without thumbnail generation', result.stdout)

    def test_optional_packages_can_all_be_declined(self):
        self.provide('gi', 'gtk4')
        result = self.preflight(answers='\n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('Permission not granted'), 2)
        self.assertIn('Continuing with your current terminal', result.stdout)
        self.assertEqual(self.commands(), [])

    def test_missing_python_is_installed_with_gui_packages(self):
        self.python.unlink()
        result = self.preflight('arch', 'y\nn\nn\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('settings window): not checked', result.stdout)
        self.assertEqual(self.commands(), [['pacman', '-S', '--needed', 'python', 'python-gobject', 'gtk4']])

    def test_unusable_system_python_aborts_without_running_a_manager(self):
        self.write_executable(self.python, '#!/bin/bash\nexit 1\n')
        result = self.preflight(answers='y\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('3.11+ required', result.stdout)
        self.assertIn('before copying any fun files', result.stderr)
        self.assertEqual(self.commands(), [])

    def test_gi_alone_does_not_pass_gtk4_check(self):
        self.provide('gi')
        result = self.preflight(answers='y\n', NO_INSTALL='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('settings window): missing', result.stdout)
        self.assertIn('GTK4 import check still fails', result.stderr)
        self.assertEqual(self.commands(), [['apt', 'install', 'python3-gi', 'gir1.2-gtk-4.0']])

    def test_gtk_without_content_fit_does_not_pass(self):
        self.provide('gi', 'gtk4', 'old-gtk')
        result = self.preflight()
        self.assertEqual(result.returncode, 1)
        self.assertIn('settings window): missing', result.stdout)
        self.assertEqual(self.commands(), [])

    def test_failed_required_package_command_stops(self):
        result = self.preflight(answers='y\ny\ny\n', FAIL_PACKAGE='gir1.2-gtk-4.0')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Package command failed (exit 42)', result.stderr)
        self.assertNotIn('Install Pillow', result.stdout)
        self.assertEqual(len(self.commands()), 1)

    def test_failed_recommended_package_command_continues(self):
        self.provide('gi', 'gtk4')
        result = self.preflight(answers='y\nn\n', FAIL_PACKAGE='python3-pil')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Package command failed (exit 42)', result.stderr)
        self.assertIn('Continuing without thumbnail generation', result.stdout)
        self.assertIn('FUN_TERMINAL', result.stdout)
        self.assertEqual(self.commands(), [['apt', 'install', 'python3-pil']])

    def test_unsupported_distro_prints_manual_checks_without_running_a_manager(self):
        result = self.preflight('opensuse', 'y\ny\ny\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('unavailable for distro ID opensuse', result.stdout)
        self.assertIn('Gtk and Gdk 4.0 typelibs', result.stdout)
        self.assertIn(f'{self.python} -c', result.stdout)
        self.assertEqual(self.commands(), [])

    def test_missing_manager_has_distro_package_guidance(self):
        (self.bin / 'dnf').unlink()
        result = self.preflight('fedora', 'y\ny\ny\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('dnf was not found', result.stdout)
        self.assertIn('python3-gobject gtk4', result.stdout)
        self.assertEqual(self.commands(), [])

    def test_unsupported_distro_with_required_dependencies_can_continue(self):
        self.provide('gi', 'gtk4')
        result = self.preflight('opensuse')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Automatic package installation is unavailable', result.stdout)
        self.assertIn('Continuing without thumbnail generation', result.stdout)
        self.assertEqual(self.commands(), [])


if __name__ == '__main__':
    unittest.main()
