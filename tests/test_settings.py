import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fun_app import settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = self.home / '.config/fun/settings.toml'
        self.config.parent.mkdir(parents=True)
        self.enterContext(patch.object(settings, 'FILE', self.config))
        self.diagnostics = self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def test_invalid_types_and_values_preserve_other_settings(self):
        fields = {'quality': ('[]', '{}', '2', 'false', '"max"'),
                  'order': ('[]', '{}', 'false', '"other"'),
                  'idle_minutes': ('{}', 'false', 'nan', '0', '1441'),
                  'minutes': ('[]', 'true', 'inf'),
                  'charging_only': ('"false"', '1'), 'scenes': ('[]', '[{}]', '["koi","koi"]')}
        for key, values in fields.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.config.write_text(f'idle_enabled=false\n{key}={value}\n')
                    result = settings.load(['koi'])
                    self.assertEqual(result[key], settings.DEFAULTS[key])
                    self.assertFalse(result['idle_enabled'])
                    self.assertIn(key, self.diagnostics.getvalue())

    def test_missing_malformed_unknown_and_valid(self):
        self.assertEqual(settings.load(), settings.DEFAULTS)
        for content in (b'bad=[', b'quality=\xff'):
            self.config.write_bytes(content)
            self.assertEqual(settings.load(), settings.DEFAULTS)
        self.config.write_text('unknown=1\nquality="high"\norder="sequential"\nminutes=12\n'
                               'idle_minutes=3.5\nidle_enabled=false\nscenes=["koi","synthwave"]\n')
        result = settings.load(['koi'])
        self.assertEqual(result, settings.DEFAULTS | dict(scenes=['koi'], minutes=12, idle_minutes=3.5,
                         quality='high', order='sequential', idle_enabled=False))
        self.assertIn('unknown', self.diagnostics.getvalue())
        settings.save(result, ['koi'])
        self.assertEqual(settings.load(['koi']), result)

    def test_invalid_config_at_idle_and_launcher_entry_points(self):
        root = Path(__file__).resolve().parents[1]
        self.config.write_text('quality=[]\nidle_minutes={}\n')
        env = dict(HOME=str(self.home), PATH=os.defpath)
        for args in ([root / 'fun-idle', '--help'], [root / 'fun', '--list']):
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('quality', result.stderr)
