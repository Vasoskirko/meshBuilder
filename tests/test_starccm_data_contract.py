import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from mesh_core import MeshParams, generate_mesh
from yplus_calculator import calculate_yplus_and_step, export_yplus_data
from starccm_macro_generator import generate_starccm_java_macro
from starccm_export_dialog import StarCcmExportDialog

class ExportDataTests(unittest.TestCase):
    def test_real_calculator_reaches_macro_and_preview(self):
        app = QApplication.instance() or QApplication([])
        data = calculate_yplus_and_step('velocity', 2, 1000, .001, 5, 10, y_plus=2)
        result = generate_mesh(MeshParams(ni=8, nj=20, nz=1))
        macro = generate_starccm_java_macro('mesh.xyz', result, None,
            {'density':1000, 'dyn_vis':.001}, data, {})
        self.assertIn('"Re_in", 10000.0,', macro)
        self.assertIn('"y_plus_target", 2.00,', macro)
        self.assertIn('"h1_wall", ' + f'{data["delta_y1_um"]*1e-6:.3e}', macro)
        self.assertIn('"kinvis", 1.000000e-06', macro)
        dialog = StarCcmExportDialog(mesh_result=result, yplus_data=data)
        try:
            self.assertEqual(dialog.yplus_data['velocity'], 2)
            self.assertEqual(dialog.yplus_data['reynolds'], 10000)
        finally:
            dialog.deleteLater()
    def test_legacy_keys_and_defaults(self):
        normalized=export_yplus_data({'reynolds':3000,'velocity':1,'delta_y1_m':1e-5,'y_plus':3})
        self.assertAlmostEqual(normalized['delta_y1_um'],10)
        self.assertEqual(export_yplus_data({},8e-6)['delta_y1_m'],8e-6)
        for bad in (float('nan'),float('inf'),0,-1):
            with self.assertRaises(ValueError):export_yplus_data({'re':bad})
