import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QWidget
from bundle_subchannel_builder import BundleBuilderWindow
from mesh_quality_dialog import QualityDialog
from starccm_export_dialog import StarCcmExportDialog


class GuiStateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def keep(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget

    def parent_with_height(self, height):
        parent = self.keep(QWidget())
        field = Mock()
        field.value.return_value = height
        parent.mesh_subpanel = SimpleNamespace(fields={'z_len': field})
        return parent, field

    def test_built_mesh_height_takes_precedence_over_ui(self):
        parent, field = self.parent_with_height(0.2)
        result = SimpleNamespace(params=SimpleNamespace(z_len=0.05), subchannels_count=2)
        dialog = self.keep(StarCcmExportDialog(parent, mesh_result=result))
        self.assertEqual(dialog.lz_m, result.params.z_len)
        self.assertEqual(field.value.return_value, 0.2)
        self.assertIn('50.0', dialog.lbl_dz_hint.text())

    def test_ui_height_used_without_built_mesh(self):
        parent, field = self.parent_with_height(0.2)
        dialog = self.keep(StarCcmExportDialog(parent))
        self.assertEqual(dialog.lz_m, 0.2)
        field.value.assert_called_once_with()

    def test_mesh_height_used_without_parent(self):
        result = SimpleNamespace(params=SimpleNamespace(z_len=0.075), subchannels_count=1)
        dialog = self.keep(StarCcmExportDialog(mesh_result=result))
        self.assertEqual(dialog.lz_m, 0.075)

    def test_quality_save_delegates_exact_report(self):
        parent = self.keep(QWidget())
        parent.save_quality_report = Mock()
        report = {'sentinel': 'unchanged'}
        receiver = SimpleNamespace(parent=lambda: parent, report=report)
        QualityDialog.save(receiver)
        parent.save_quality_report.assert_called_once_with(report)
        self.assertIs(parent.save_quality_report.call_args.args[0], report)

    def test_bundle_parent_provides_quality_save_callback(self):
        window = self.keep(BundleBuilderWindow())
        self.assertTrue(callable(getattr(window, 'save_quality_report', None)),
                        'BundleBuilderWindow must provide the callback invoked by QualityDialog.save')


if __name__ == '__main__':
    unittest.main()
