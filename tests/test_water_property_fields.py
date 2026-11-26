"""Water enthalpy/saturation units and read-only GUI property fields."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fluid_properties import water_iapws97,_saturation_pressure_mpa
from PySide6.QtWidgets import QApplication
from yplus_dialog import YPlusDialog

class WaterPropertyFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def dialog(self,**state):
        d=YPlusDialog(state_dict={'temp_c':'300','press_mpa':'15',**state})
        self.addCleanup(d.deleteLater);return d
    def test_if97_region1_enthalpy_units_and_saturation_identities(self):
        for T,P,h in [(300,3,115331.273),(500,3,975542.239)]:
            self.assertAlmostEqual(water_iapws97(T-273.15,P)['enthalpy'],h,delta=.001)
        r=water_iapws97(300,15)
        self.assertAlmostEqual(r['enthalpy']/1000,1338.063260953498,places=8)
        self.assertAlmostEqual(r['saturation_pressure_mpa'],8.587708329557264,places=10)
        self.assertAlmostEqual(r['saturation_temperature_c'],342.15787124898213,places=8)
        self.assertEqual(r['subcooling_k'],r['saturation_temperature_c']-300)
        self.assertEqual(r['pressure_margin_mpa'],15-r['saturation_pressure_mpa'])
        self.assertGreater(r['saturated_liquid_density'],r['saturated_vapor_density'])
        self.assertGreater(r['latent_heat'],0)
        self.assertAlmostEqual(r['latent_heat'],r['saturated_vapor_enthalpy']-r['saturated_liquid_enthalpy'],places=8)
    def test_reference_saturation_does_not_extend_main_region_and_handles_limits(self):
        for p in (22.064,25,100):
            r=water_iapws97(300,p)
            self.assertIsNone(r['saturation_temperature_c']);self.assertIsNone(r['latent_heat'])
            self.assertIsNone(r['subcooling_k']);self.assertGreater(r['pressure_margin_mpa'],0)
            self.assertIn('22.064',r['saturation_status'])
        r=water_iapws97(0,_saturation_pressure_mpa(273.15))
        self.assertIsNone(r['saturation_temperature_c']);self.assertIn('тройной',r['saturation_status'])
        r=water_iapws97(350,20)
        self.assertGreater(r['saturation_temperature_c'],350)
        with self.assertRaises(ValueError):water_iapws97(360,20)
        r=water_iapws97(100,_saturation_pressure_mpa(373.15))
        self.assertEqual(r['subcooling_k'],0);self.assertEqual(r['pressure_margin_mpa'],0)
    def test_conductivity_choice_preserves_enthalpy_and_saturation(self):
        background=water_iapws97(290,16.2)
        full=water_iapws97(290,16.2,conductivity_model='full')
        for key in ('enthalpy','saturation_temperature_c','saturation_pressure_mpa','latent_heat'):
            self.assertEqual(background[key],full[key])
    def test_gui_fields_are_readonly_and_convert_enthalpy_to_kj(self):
        d=self.dialog();r=d.current_fluid_props
        self.assertTrue(d.btn_apply.isEnabled())
        for field in (*d.properties_dialog.property_fields.values(),*d.properties_dialog.saturation_fields.values()):self.assertTrue(field.isReadOnly())
        self.assertAlmostEqual(float(d.properties_dialog.property_fields['enthalpy'].text()),r['enthalpy']/1000,places=4)
        self.assertAlmostEqual(float(d.properties_dialog.property_fields['kin_vis'].text()),r['dyn_vis']/r['density'],places=14)
        self.assertAlmostEqual(float(d.properties_dialog.saturation_fields['latent_heat'].text()),r['latent_heat']/1000,places=4)
        self.assertIn('IF97',d.properties_dialog.property_fields['enthalpy'].toolTip())
        d.edit_press.setText('25');d.recalc()
        self.assertEqual(d.properties_dialog.saturation_fields['saturation_temperature_c'].text(),'')
        self.assertIn('22.064',d.properties_dialog.saturation_note.text())
    def test_invalid_inputs_and_mode_changes_clear_stale_properties(self):
        d=self.dialog();self.assertNotEqual(d.properties_dialog.property_fields['enthalpy'].text(),'')
        d.edit_temp.setText('400');d.recalc()
        self.assertFalse(d.btn_apply.isEnabled());self.assertEqual(d.current_fluid_props,{})
        self.assertEqual(d.properties_dialog.property_fields['enthalpy'].text(),'')
        self.assertEqual(d.properties_dialog.saturation_fields['saturation_pressure_mpa'].text(),'')
        d.edit_temp.setText('300');d.recalc();self.assertTrue(d.btn_apply.isEnabled())
        d.combo_fluid_mode.setCurrentIndex(1)
        self.assertTrue(d.properties_dialog.saturation_group.isHidden())
        self.assertEqual(d.properties_dialog.property_fields['enthalpy'].text(),'')
        self.assertNotEqual(d.properties_dialog.property_fields['cp'].text(),'')
        d.combo_fluid_mode.setCurrentIndex(3)
        self.assertEqual(d.properties_dialog.property_fields['cp'].text(),'')
        self.assertEqual(d.properties_dialog.property_fields['lambda'].text(),'')
        self.assertNotEqual(d.properties_dialog.property_fields['kin_vis'].text(),'')

    def test_properties_window_is_separate_live_and_does_not_apply_h1(self):
        d=self.dialog();d.show();self.app.processEvents()
        self.addCleanup(d.close)
        self.assertFalse(d.properties_dialog.isVisible())
        self.assertIs(d.edit_density.window(),d)
        self.assertIs(d.properties_dialog.property_fields['enthalpy'].window(),d.properties_dialog)
        d.open_properties();self.app.processEvents()
        detail=d.properties_dialog;self.assertTrue(detail.isVisible())
        d.edit_temp.setText('290');d.edit_press.setText('16.2');d.recalc()
        self.assertEqual(detail.props['t_ref_c'],290)
        self.assertEqual(detail.props['p_ref_mpa'],16.2)
        self.assertEqual(detail.props,d.current_fluid_props)
        h1=d.calculated_delta_y1_um
        detail.combo_conductivity.setCurrentIndex(detail.combo_conductivity.findData('full'))
        self.assertEqual(d.current_fluid_props['conductivity_model'],'full')
        self.assertEqual(d.calculated_delta_y1_um,h1)
        saved=dict(d.state_dict);detail.close();self.app.processEvents()
        self.assertEqual(d.state_dict,saved);self.assertTrue(d.isVisible())
        d.open_properties();self.assertIs(d.properties_dialog,detail)
        d.reject();self.app.processEvents();self.assertFalse(detail.isVisible())
    def test_current_star_export_ui_is_present_alongside_property_dialog(self):
        from starccm_export_dialog import StarCcmExportDialog
        d=self.dialog();export=StarCcmExportDialog()
        self.addCleanup(export.deleteLater)
        self.assertEqual(export.tabs.count(),8)
        self.assertTrue(hasattr(export,'combo_gravity'))
        self.assertTrue(hasattr(export,'report_checkboxes'))
        self.assertTrue(hasattr(export,'mean_checkboxes'))
        self.assertTrue(hasattr(export,'field_checkboxes'))
        self.assertTrue(hasattr(export,'save_export_profile'))
