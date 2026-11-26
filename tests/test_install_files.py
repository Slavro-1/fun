"""Exercise the two real transactions with an in-process, unprivileged system worker."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from installer import install_files as setup


class FileTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.addCleanup(os.umask, os.umask(0o022))
        self.prefix = self.home / 'prefix'
        self.src = self.home / 'source'
        for name in setup.SOURCES:
            path = self.src / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text('source ' + name)
        self.enterContext(patch.object(setup, 'PREFIX', self.prefix))
        self.enterContext(patch.object(setup, 'ROOT', self.src))
        self.enterContext(patch.dict(os.environ, dict(HOME=str(self.home),
                         XDG_CONFIG_HOME=str(self.home / 'config'), XDG_DATA_HOME=str(self.home / 'data'))))
        self.enterContext(patch.object(setup, 'system_worker', side_effect=self.worker))
        self.enterContext(patch('sys.stdin', io.StringIO()))
        self.log = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.exe = self.prefix / 'bin/fun'
        self.entry = self.home / 'config/autostart/fun-idle.desktop'
        self.record = self.prefix / 'lib/fun/ownership.json'

    def worker(self, action):
        return setup.prepared(action, system=True)

    def test_install_upgrade_and_repeat(self):
        setup.operate('install')
        ino = self.exe.stat().st_ino
        setup.operate('install')
        self.assertEqual(ino, self.exe.stat().st_ino)
        (self.src / 'fun').write_text('updated')
        setup.operate('install')
        self.assertEqual(self.exe.read_text(), 'updated')
        backup, = self.exe.parent.glob('fun.bak-*')
        self.assertEqual(backup.read_text(), 'source fun')
        for _ in range(2):
            setup.operate('uninstall')
        self.assertFalse(self.exe.exists())
        self.assertFalse(self.entry.exists())
        self.assertTrue(backup.is_file())

    def test_upgrade_from_flat_program_manifest(self):
        legacy_paths = {
            'bin/fun', 'bin/fun-idle', 'bin/fun-config', 'lib/fun/extras.py',
            'lib/fun/fun_settings.py', 'lib/fun/fun_wayland.py', 'lib/fun/fun_runtime.py',
            'lib/fun/fun_session.py', 'lib/fun/snap.py',
        }
        legacy_sources = {src: dst for src, dst in setup.SOURCES.items() if dst in legacy_paths}
        self.assertEqual(set(legacy_sources.values()), legacy_paths)
        with patch.object(setup, 'SOURCES', legacy_sources):
            setup.operate('install')
        registry = self.prefix / 'lib/fun/fun_app/scenes/registry.py'
        self.assertFalse(registry.exists())

        setup.operate('install')
        manifest = json.loads(self.record.read_text())
        self.assertEqual(set(manifest['files']), {str(self.prefix / dst) for dst in setup.SOURCES.values()})
        self.assertEqual(registry.read_text(), 'source fun_app/scenes/registry.py')
        setup.operate('uninstall')
        self.assertFalse(registry.exists())
        self.assertTrue(all(not (self.prefix / dst).exists() for dst in legacy_paths))

    def test_legacy_requires_explicit_adoption(self):
        self.exe.parent.mkdir(parents=True)
        self.exe.write_text('earlier copy')
        with self.assertRaisesRegex(setup.Conflict, 'declined'):
            setup.operate('install')
        self.assertEqual(self.exe.read_text(), 'earlier copy')
        self.assertFalse(self.entry.exists())
        with patch('sys.stdin', io.StringIO('ADOPT\n')):
            setup.operate('install')
        backup, = self.exe.parent.glob('fun.bak-*')
        self.assertEqual(backup.read_text(), 'earlier copy')

    def test_autostart_conflict_preserves_working_program(self):
        setup.operate('install')
        (self.src / 'fun').write_text('upgrade')
        self.entry.write_text('custom')
        with self.assertRaises(setup.Conflict):
            setup.operate('install')
        self.assertEqual(self.exe.read_text(), 'source fun')
        self.assertEqual(self.entry.read_text(), 'custom')

    def test_post_preflight_failure_rolls_back_both_scopes(self):
        setup.operate('install')
        self.entry.unlink()  # user transaction will recreate this
        before = self.record.read_bytes()
        ino = self.exe.stat().st_ino
        for name in ('fun', 'fun-idle'):
            (self.src / name).write_text('updated')
        replace = setup.Files.replace

        def fail(fs, src, dst):
            if dst == self.exe.with_name('fun-idle'):
                raise OSError('injected replacement failure')
            replace(fs, src, dst)

        with patch.object(setup.Files, 'replace', fail), self.assertRaisesRegex(OSError, 'injected'):
            setup.operate('install')
        self.assertEqual(self.exe.stat().st_ino, ino)
        self.assertEqual(self.exe.read_text(), 'source fun')
        self.assertEqual(self.exe.with_name('fun-idle').read_text(), 'source fun-idle')
        self.assertEqual(self.record.read_bytes(), before)
        self.assertFalse(self.entry.exists())
        self.assertFalse(list(self.home.rglob('.fun-stage-*')))

    def test_changed_and_replaced_files_survive(self):
        setup.operate('install')
        self.exe.write_text('mine')
        other = self.exe.with_name('fun-idle')
        substitute = other.with_suffix('.new')
        substitute.write_bytes(other.read_bytes())
        substitute.chmod(0o755)
        substitute.replace(other)
        with self.assertRaisesRegex(setup.Conflict, 'changed'):
            setup.operate('install')
        setup.operate('uninstall')
        self.assertEqual(self.exe.read_text(), 'mine')
        self.assertTrue(other.exists())
        self.assertIn('modified or unowned', self.log.getvalue())

    def test_missing_and_malformed_manifest(self):
        setup.operate('install')
        self.record.write_text('{"format":"fun-install-1","files":{"/other":[]}}')
        with self.assertRaisesRegex(setup.Conflict, 'Unexpected paths'):
            setup.operate('uninstall')
        self.assertTrue(self.entry.exists())
        self.record.write_text('{')
        with self.assertRaises(json.JSONDecodeError):
            setup.operate('install')
        self.record.unlink()
        setup.operate('uninstall')
        self.assertTrue(self.exe.exists())

    def test_disk_error_staging_leaves_both_installations_intact(self):
        setup.operate('install')
        original = self.record.read_bytes()
        (self.src / 'fun').write_text('update')
        with patch.object(setup.Files, 'stage', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                setup.operate('install')
        self.assertEqual(self.record.read_bytes(), original)
        self.assertEqual(self.exe.read_text(), 'source fun')
        self.assertTrue(self.entry.exists())

    def test_recheck_before_commit_retains_new_occupant(self):
        with setup.prepared('install', system=True) as (_, commit):
            self.exe.write_text('created since preflight')
            with self.assertRaisesRegex(setup.Conflict, 'changed since preflight'):
                commit()
        self.assertEqual(self.exe.read_text(), 'created since preflight')
        self.assertFalse(self.record.exists())

    def test_concurrent_program_transaction_refused(self):
        with setup.prepared('install', system=True):
            with self.assertRaises(BlockingIOError):
                setup.operate('install')
        self.assertFalse(self.exe.exists())
        self.assertFalse(self.entry.exists())

    def test_untrusted_system_directory_and_manifest_symlink(self):
        self.prefix.mkdir(mode=0o755)
        self.prefix.chmod(0o777)
        with self.assertRaisesRegex(setup.Conflict, 'permissions'):
            setup.operate('install')
        self.prefix.chmod(0o755)
        setup.operate('install')
        self.record.unlink()
        self.record.symlink_to(self.exe)
        with self.assertRaisesRegex(setup.Conflict, 'file type'):
            setup.operate('uninstall')
        self.assertTrue(self.record.is_symlink())
        self.assertEqual(self.exe.read_text(), 'source fun')
        self.assertTrue(self.entry.exists())

    def test_symlink_file_and_ancestor(self):
        self.exe.parent.mkdir(parents=True)
        victim = self.home / 'keep'
        victim.write_text('mine')
        self.exe.symlink_to(victim)
        with self.assertRaisesRegex(setup.Conflict, 'file type'):
            setup.operate('install')
        setup.operate('uninstall')
        self.assertTrue(self.exe.is_symlink())
        self.exe.unlink()
        (self.prefix / 'lib').symlink_to(self.home)
        with self.assertRaises(OSError):
            setup.operate('install')
        self.assertFalse((self.home / 'fun').exists())
        self.assertEqual(victim.read_text(), 'mine')

    def test_custom_legacy_desktop_with_matching_exec_is_preserved(self):
        self.entry.parent.mkdir(parents=True)
        self.entry.write_text(setup.OLD_STARTUP.format(prefix=self.prefix) + 'Hidden=true\n')
        with self.assertRaisesRegex(setup.Conflict, 'Unrecognized'):
            setup.operate('install')
        self.assertFalse(self.exe.exists())
