import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from number_field import NumberField
from bundle_subchannel_builder import BundleBuilderWindow

class NumberFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_invalid_draft_is_visible_and_never_replaces_value(self):
        f=NumberField(2.5e-6,1e-6,1e-18,1)
        for text in ('abc','','nan','inf','-1','1e99'):
            with self.subTest(text=text):
                f.setText(text)
                with self.assertRaises(ValueError):f.value()
                f._finish()
                self.assertEqual(f.text(),text)
                self.assertEqual(f.model.raw,2.5e-6)
                self.assertIn('c33',f.styleSheet())
        f.deleteLater()
    def test_valid_formats_and_unit_changes(self):
        f=NumberField(2.5e-6,1e-6)
        for text in ('3,5','3.5','3.5e0'):
            f.setText(text);self.assertAlmostEqual(f.value(),3.5e-6)
        f.setFactor(1e-3);self.assertAlmostEqual(f.value(),3.5e-6)
        f.setValue(1.234567890123456e-6)
        self.assertEqual(f.value(),1.234567890123456e-6)
        f.deleteLater()
    def test_bundle_invalid_edit_does_not_raise_from_signal_or_build(self):
        w=BundleBuilderWindow()
        try:
            sid=next(k for k,s in w.model.subchannels.items() if s.sub_type=='interior')
            w.model.selected_subchannels={sid}
            field=w.mesh_subpanel.fields['h1'];field.setText('abc');field.edited.emit()
            with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:
                w.on_build_multiblock_mesh()
                warning.assert_called_once()
            self.assertFalse(w.can_export_mesh())
            self.assertIsNone(w.current_layer_result)
        finally:w.deleteLater()
