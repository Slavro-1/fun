"""Focused, display-free checks for the GTK scene inventory and count."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


from fun_app.gui import config
from fun_app.scenes import registry


class CountTests(unittest.TestCase):
    def test_inventory_uses_only_active_registry(self):
        names = config.scene_names()
        self.assertEqual(names, list(registry.SCENES))
        self.assertFalse(set(names) & set(registry.ALIASES))
        self.assertFalse(set(names) & config.settings.RETIRED_SCENES)

    def test_retired_names_are_excluded_from_list_output(self):
        output = 'aurora\nsynthwave\nkoi\n'
        with patch.object(config.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            self.assertEqual(config.scene_names(), ['aurora', 'koi'])

    def test_thumbnail_signature_with_optional_preview_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / 'preview.py'
            with patch.object(config, 'SNAP', preview):
                no_preview = config.preview_signature()
                self.assertRegex(no_preview, r'^[0-9a-f]+-[0-9a-f]+$')
                preview.write_text('# preview generator')
                self.assertNotEqual(config.preview_signature(), no_preview)

    def test_thumbnail_cleanup_preserves_linked_and_unrelated_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('artwork', '1a-2b'):
                (root / name).mkdir()
                (root / name / 'pulsar.png').write_bytes(b'keep artwork outside version cache')
            (root / '3c-4d').symlink_to(root / 'artwork')
            config.prune_retired_thumbnails(root)
            self.assertTrue((root / 'artwork/pulsar.png').exists())
            self.assertFalse((root / '1a-2b/pulsar.png').exists())

    def test_search_does_not_change_total_or_enabled_count(self):
        names = config.scene_names()
        selected = set(names[::2])
        expected = (len(selected), f'{len(selected)} of {len(names)} enabled')
        for query in ('', 'aurora', 'no matching scene'):
            visible = [name for name in names if query in name]
            if query:
                self.assertNotEqual(visible, names)
            self.assertEqual(config.count_status(names, selected), expected)
        self.assertEqual(config.count_status(names, set()), (0, f'0 of {len(names)} enabled'))


if __name__ == '__main__':
    unittest.main()
