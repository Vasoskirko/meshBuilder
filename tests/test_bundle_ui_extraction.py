"""Verify mechanical relocation against the pre-refactor commit."""
import ast
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = '5f957d88cf1e416ce488ecf849041d29a3ff1f14'
MOVED = {'init_ui', 'add_double_spin'}


def find_class(tree, name):
    matches = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    if len(matches) != 1:
        raise AssertionError('Expected one class: ' + name)
    return matches[0]


class BundleUiExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = ast.parse(subprocess.check_output(
            ['git', 'show', BASE + ':bundle_subchannel_builder.py'], cwd=ROOT).decode('utf-8'))

    def test_moved_method_bodies_are_unchanged(self):
        original = find_class(self.original, 'BundleBuilderWindow')
        extracted = find_class(ast.parse(subprocess.check_output(['git','show','e2f362c:bundle_builder_ui.py'],cwd=ROOT).decode('utf-8')), 'BundleBuilderUiMixin')
        before = {n.name: n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in MOVED}
        after = {n.name: n for n in extracted.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(before), MOVED)
        self.assertEqual(set(after), MOVED)
        for name in MOVED:
            with self.subTest(method=name):
                self.assertEqual(ast.dump(before[name], include_attributes=False), ast.dump(after[name], include_attributes=False))

    def test_extraction_commit_preserved_remaining_source(self):
        expected = copy.deepcopy(self.original)
        cls = find_class(expected, 'BundleBuilderWindow')
        cls.body = [n for n in cls.body if not (isinstance(n, ast.FunctionDef) and n.name in MOVED)]
        cls.bases.insert(0, ast.Name(id='BundleBuilderUiMixin', ctx=ast.Load()))
        expected.body.insert(expected.body.index(cls), ast.parse('from bundle_builder_ui import BundleBuilderUiMixin').body[0])
        actual = ast.parse(subprocess.check_output(
            ['git', 'show', 'e2f362c:bundle_subchannel_builder.py'], cwd=ROOT).decode('utf-8'))
        self.assertEqual(ast.dump(expected, include_attributes=False), ast.dump(actual, include_attributes=False))

    def test_legacy_import_exposes_inherited_methods(self):
        from bundle_subchannel_builder import BundleBuilderWindow
        from bundle_builder_ui import BundleBuilderUiMixin
        self.assertTrue(issubclass(BundleBuilderWindow, BundleBuilderUiMixin))
        for name in MOVED:
            self.assertIs(getattr(BundleBuilderWindow, name), getattr(BundleBuilderUiMixin, name))

    def test_window_constructs_offscreen(self):
        from PySide6.QtWidgets import QApplication
        from bundle_subchannel_builder import BundleBuilderWindow
        app = QApplication.instance() or QApplication([])
        window = BundleBuilderWindow()
        try:
            self.assertIsNotNone(window.centralWidget())
            self.assertEqual(window.tabs.count(), 3)
            self.assertIs(window.mesh_subpanel.parent_window, window)
            self.assertIn('z_len', window.mesh_subpanel.fields)
            self.assertFalse(window.mesh_subpanel.btn_export.isEnabled())
            app.processEvents()
        finally:
            window.deleteLater()


if __name__ == '__main__':
    unittest.main()
