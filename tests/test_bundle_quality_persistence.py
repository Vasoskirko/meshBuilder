import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QWidget
from bundle_subchannel_builder import BundleBuilderWindow
from starccm_export_dialog import StarCcmExportDialog


class BundleQualityPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = BundleBuilderWindow()
        self.addCleanup(self.window.deleteLater)
        self.path = Path(self.temp.name) / 'quality.json'
        self.report = {'sentinel': 'Отчёт', 'metrics': {}, 'version': 1}
        self.window.current_quality_report = self.report

    def test_save_writes_json_without_mutating_state(self):
        mesh = self.window.current_mesh_result
        params = self.window.base_params
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName', return_value=(str(self.path), '')), patch('bundle_subchannel_builder.QMessageBox.information') as info, patch('bundle_subchannel_builder.QMessageBox.critical') as error:
            saved = self.window.save_quality_report(self.report)
        self.assertEqual(saved, str(self.path))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), self.report)
        self.assertIs(self.window.current_quality_report, self.report)
        self.assertIs(self.window.current_mesh_result, mesh)
        self.assertIs(self.window.base_params, params)
        info.assert_called_once()
        error.assert_not_called()

    def test_cancel_does_not_write(self):
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName', return_value=('', '')), patch('bundle_subchannel_builder.mq.save_report') as writer, patch('bundle_subchannel_builder.QMessageBox.information') as info:
            self.assertIsNone(self.window.save_quality_report(self.report))
        writer.assert_not_called()
        info.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_write_error_is_reported_and_existing_file_preserved(self):
        self.path.write_text('ORIGINAL', encoding='utf-8')
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName', return_value=(str(self.path), '')), patch('bundle_subchannel_builder.mq.save_report', side_effect=OSError('synthetic write error')), patch('bundle_subchannel_builder.QMessageBox.critical') as error, patch('bundle_subchannel_builder.QMessageBox.information') as info:
            self.assertIsNone(self.window.save_quality_report(self.report))
        error.assert_called_once()
        info.assert_not_called()
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'ORIGINAL')

    def test_legacy_mesh_height_takes_precedence_over_ui(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.mesh_subpanel = SimpleNamespace(fields={'z_len': SimpleNamespace(value=lambda: 0.2)})
        result = SimpleNamespace(params=SimpleNamespace(L=0.075), subchannels_count=1)
        dialog = StarCcmExportDialog(parent, mesh_result=result)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.lz_m, 0.075)


if __name__ == '__main__':
    unittest.main()
