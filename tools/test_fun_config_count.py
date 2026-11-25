"""Focused, display-free checks for the GTK scene inventory and count."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = load('fun_config_count_test', ROOT / 'fun-config')
        cls.renderer = load('extras_count_test', ROOT / 'extras.py')

    def test_inventory_uses_only_active_registry(self):
        names = self.gui.scene_names()
        self.assertEqual(names, list(self.renderer.SCENES))
        self.assertFalse(set(names) & set(self.renderer.ALIASES))
        self.assertFalse(set(names) & self.gui.settings.RETIRED_SCENES)

    def test_retired_names_are_excluded_from_list_output(self):
        output = 'aurora\nsynthwave\nkoi\n'
        with patch.object(self.gui.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            self.assertEqual(self.gui.scene_names(), ['aurora', 'koi'])

    def test_thumbnail_cleanup_preserves_linked_and_unrelated_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('artwork', '1a-2b'):
                (root / name).mkdir()
                (root / name / 'pulsar.png').write_bytes(b'keep artwork outside version cache')
            (root / '3c-4d').symlink_to(root / 'artwork')
            self.gui.prune_retired_thumbnails(root)
            self.assertTrue((root / 'artwork/pulsar.png').exists())
            self.assertFalse((root / '1a-2b/pulsar.png').exists())

    def test_search_does_not_change_total_or_enabled_count(self):
        names = self.gui.scene_names()
        selected = set(names[::2])
        expected = (len(selected), f'{len(selected)} of {len(names)} enabled')
        for query in ('', 'aurora', 'no matching scene'):
            visible = [name for name in names if query in name]
            if query:
                self.assertNotEqual(visible, names)
            self.assertEqual(self.gui.count_status(names, selected), expected)
        self.assertEqual(self.gui.count_status(names, set()), (0, f'0 of {len(names)} enabled'))


if __name__ == '__main__':
    unittest.main()
