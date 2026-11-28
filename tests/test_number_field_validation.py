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
    def test_spinbox_both_decimal_marks_in_russian_and_english_locales(self):
        from PySide6.QtCore import QLocale,Qt
        from PySide6.QtTest import QTest
        from PySide6.QtGui import QValidator
        from decimal_spinbox import DecimalSpinBox
        spin=DecimalSpinBox();spin.setRange(0,300);spin.setDecimals(3)
        try:
            for locale in ('ru_RU','en_US'):
                spin.setLocale(QLocale(locale))
                for text in ('12.75','12,75'):
                    with self.subTest(locale=locale,text=text):
                        spin.setValue(1);spin.lineEdit().selectAll();QTest.keyClicks(spin.lineEdit(),text);QTest.keyClick(spin.lineEdit(),Qt.Key_Return)
                        self.assertAlmostEqual(spin.value(),12.75)
                for text in ('12,7.5','12..75','12,,75'):
                    self.assertEqual(spin.validate(text,len(text))[0],QValidator.Invalid)
            spin.setValue(12.75);spin.stepUp();self.assertAlmostEqual(spin.value(),13.75)
        finally:spin.deleteLater()
    def test_bundle_geometry_inputs_accept_dot_with_russian_locale(self):
        from PySide6.QtCore import QLocale,Qt
        from PySide6.QtTest import QTest
        w=BundleBuilderWindow()
        try:
            for name,value in (('s_flat_spin',65.5),('pitch_spin',12.75),('d_fuel_spin',9.1),('d_guide_spin',12.1),('d_inst_spin',10.3)):
                spin=getattr(w,name);spin.setLocale(QLocale('ru_RU'));spin.lineEdit().selectAll();QTest.keyClicks(spin.lineEdit(),str(value));QTest.keyClick(spin.lineEdit(),Qt.Key_Return)
                self.assertAlmostEqual(spin.value(),value)
        finally:w.close();w.deleteLater()
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
