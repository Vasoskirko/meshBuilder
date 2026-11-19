import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from starccm_export_dialog import StarCcmExportDialog


class ExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.macro = Path(self.temp.name) / 'setup.java'
        result = SimpleNamespace(params=SimpleNamespace(z_len=0.05), subchannels_count=2)
        self.dialog = StarCcmExportDialog(mesh_result=result)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.dialog.deleteLater()
        self.app.processEvents()

    def run_export(self, selected, generator_error=None):
        def export(result, path, **kwargs):
            Path(path).write_text('XYZ sentinel', encoding='utf-8')

        with patch('starccm_export_dialog.QFileDialog.getSaveFileName', return_value=(selected, '')), patch('mesh_subchannel.export_subchannel_plot3d', side_effect=export) as exporter, patch('starccm_macro_generator.generate_starccm_java_macro', return_value='JAVA sentinel', side_effect=generator_error) as generator, patch('starccm_export_dialog.QMessageBox.critical') as critical, patch('starccm_export_dialog.QMessageBox.warning') as warning, patch('starccm_export_dialog.QMessageBox.information') as information, patch.object(self.dialog, 'accept') as accepted:
            self.dialog.generate_and_save()
            return exporter, generator, critical, warning, information, accepted

    def test_cancel_has_no_side_effects(self):
        exporter, generator, critical, warning, information, accepted = self.run_export('')
        exporter.assert_not_called()
        generator.assert_not_called()
        accepted.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_success_writes_separate_outputs(self):
        exporter, generator, critical, warning, information, accepted = self.run_export(str(self.macro))
        self.assertEqual(self.macro.read_text(encoding='utf-8'), 'JAVA sentinel')
        self.assertEqual((self.macro.parent / 'bundle_mesh.xyz').read_text(encoding='utf-8'), 'XYZ sentinel')
        self.assertEqual(generator.call_args.kwargs['xyz_filename'], 'bundle_mesh.xyz')
        exporter.assert_called_once()
        generator.assert_called_once()
        critical.assert_not_called()
        accepted.assert_called_once()

    def test_identical_output_paths_are_rejected_before_writing(self):
        self.macro.write_text('ORIGINAL', encoding='utf-8')
        self.dialog.edit_xyz.setText(self.macro.name)
        exporter, generator, critical, warning, information, accepted = self.run_export(str(self.macro))
        self.assertEqual(self.macro.read_text(encoding='utf-8'), 'ORIGINAL')
        exporter.assert_not_called()
        generator.assert_not_called()
        accepted.assert_not_called()
        self.assertTrue(critical.called or warning.called)

    def test_generator_error_is_reported_without_escaping(self):
        self.macro.write_text('ORIGINAL', encoding='utf-8')
        exporter, generator, critical, warning, information, accepted = self.run_export(str(self.macro), RuntimeError('synthetic generation failure'))
        critical.assert_called_once()
        information.assert_not_called()
        accepted.assert_not_called()
        self.assertEqual(self.macro.read_text(encoding='utf-8'), 'ORIGINAL')


if __name__ == '__main__':
    unittest.main()
