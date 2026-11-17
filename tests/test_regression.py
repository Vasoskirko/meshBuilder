import ast
import dataclasses
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'
BASE = 'fc044b9a2f7c7408cf664b7fb9e17e12619cb726'


class RepositoryTests(unittest.TestCase):
    def test_syntax(self):
        for path in ROOT.glob('*.py'):
            with self.subTest(file=path.name):
                ast.parse(path.read_text(encoding='utf-8'), filename=str(path))

    def test_independent_imports(self):
        for path in ROOT.glob('*.py'):
            with self.subTest(module=path.stem):
                result = subprocess.run([sys.executable, '-c', 'import ' + path.stem], cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_help(self):
        result = subprocess.run([sys.executable, 'mesh_core.py', '--help'], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--settings', result.stdout)

    def test_gui_creation(self):
        script = '''from PySide6.QtWidgets import QApplication
from mesh_gui import MeshWindow
from bundle_subchannel_builder import BundleBuilderWindow
from mesh_help_dialog import HelpDialog
from bundle_hydraulics_dialog import HydraulicsTableDialog
app = QApplication([])
a = MeshWindow()
b = BundleBuilderWindow()
h = HelpDialog(a)
d = HydraulicsTableDialog(b, b.model)
app.processEvents()
for w in (d, h, b, a):
    w.deleteLater()
app.processEvents()
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CoreRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mesh_core
        cls.new = mesh_core
        source = subprocess.run(['git', 'show', BASE + ':mesh_core.py'], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        cls.temp = tempfile.TemporaryDirectory()
        path = Path(cls.temp.name) / 'baseline_core.py'
        path.write_text(source, encoding='utf-8')
        spec = importlib.util.spec_from_file_location('baseline_core', path)
        cls.old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.old
        spec.loader.exec_module(cls.old)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compare(self, a, b):
        self.assertEqual(dataclasses.asdict(a.params), dataclasses.asdict(b.params))
        self.assertEqual(len(a.blocks), len(b.blocks))
        for ba, bb in zip(a.blocks, b.blocks):
            for xa, xb in zip(ba, bb):
                np.testing.assert_array_equal(xa, xb)
        np.testing.assert_array_equal(a.layer_widths, b.layer_widths)
        self.assertEqual(a.diagnostics, b.diagnostics)

    def test_distributions(self):
        cases = [dict(law=law, mode='first_count') for law in ('geometric', 'tanh', 'sinh', 'power')]
        cases += [dict(law='uniform', mode='shape_count'), dict(law='two_zone', mode='first_count', smoothing='none', wall_layers=4)]
        cases += [dict(law='wall_core', mode=mode) for mode in ('layer_thickness', 'layer_growth', 'layer_first_growth')]
        for full in (False, True):
            for case in cases:
                with self.subTest(full=full, **case):
                    values = dict(ni=12, nj=40, nz=2, full=full, **case)
                    a = self.old.generate_mesh(self.old.MeshParams(**values))
                    b = self.new.generate_mesh(self.new.MeshParams(**values))
                    self.compare(a, b)
                    self.assertGreater(self.new.check_mesh(b)[0], 0)

    def test_fill_and_io(self):
        for full in (False, True):
            with self.subTest(full=full):
                values = dict(ni=12, nz=2, full=full, law='wall_core', mode='layer_thickness')
                a = self.old.generate_mesh(self.old.MeshParams(**values))
                b = self.new.generate_mesh(self.new.MeshParams(**values))
                before = [(x.copy(), y.copy()) for x, y in b.blocks]
                aa = self.old.fill_core(a, 1.1, 30e-6)
                bb = self.new.fill_core(b, 1.1, 30e-6)
                self.compare(aa, bb)
                for original, unchanged, completed, starts in zip(before, b.blocks, bb.blocks, b.wall_start):
                    for x, y, z in zip(original, unchanged, completed):
                        np.testing.assert_array_equal(x, y)
                        part = z[:, :x.shape[1]] if starts else z[:, -x.shape[1]:]
                        np.testing.assert_array_equal(x, part)
                with tempfile.TemporaryDirectory() as tmp:
                    pa, pb = Path(tmp) / 'a.xyz', Path(tmp) / 'b.xyz'
                    self.old.save_mesh(aa, pa)
                    self.new.save_mesh(bb, pb)
                    self.assertEqual(pa.read_bytes(), pb.read_bytes())
                    config = Path(tmp) / 'settings.json'
                    self.new.save_configuration(b.requested, 'мм', 'мкм', config)
                    loaded, gu, cu = self.new.load_configuration(config)
                    self.assertEqual(loaded, b.requested)
                    self.assertEqual((gu, cu), ('мм', 'мкм'))
                    with self.assertRaises(ValueError):
                        self.new.save_mesh(b, Path(tmp) / 'incomplete.xyz')


if __name__ == '__main__':
    unittest.main()
