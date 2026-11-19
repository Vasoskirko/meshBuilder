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
        for field in (*d.property_fields.values(),*d.saturation_fields.values()):self.assertTrue(field.isReadOnly())
        self.assertAlmostEqual(float(d.property_fields['enthalpy'].text()),r['enthalpy']/1000,places=4)
        self.assertAlmostEqual(float(d.property_fields['kin_vis'].text()),r['dyn_vis']/r['density'],places=14)
        self.assertAlmostEqual(float(d.saturation_fields['latent_heat'].text()),r['latent_heat']/1000,places=4)
        self.assertIn('IF97',d.property_fields['enthalpy'].toolTip())
        d.edit_press.setText('25');d.recalc()
        self.assertEqual(d.saturation_fields['saturation_temperature_c'].text(),'')
        self.assertIn('22.064',d.saturation_note.text())
    def test_invalid_inputs_and_mode_changes_clear_stale_properties(self):
        d=self.dialog();self.assertNotEqual(d.property_fields['enthalpy'].text(),'')
        d.edit_temp.setText('400');d.recalc()
        self.assertFalse(d.btn_apply.isEnabled());self.assertEqual(d.current_fluid_props,{})
        self.assertEqual(d.property_fields['enthalpy'].text(),'')
        self.assertEqual(d.saturation_fields['saturation_pressure_mpa'].text(),'')
        d.edit_temp.setText('300');d.recalc();self.assertTrue(d.btn_apply.isEnabled())
        d.combo_fluid_mode.setCurrentIndex(1)
        self.assertTrue(d.saturation_group.isHidden())
        self.assertEqual(d.property_fields['enthalpy'].text(),'')
        self.assertNotEqual(d.property_fields['cp'].text(),'')
        d.combo_fluid_mode.setCurrentIndex(3)
        self.assertEqual(d.property_fields['cp'].text(),'')
        self.assertEqual(d.property_fields['lambda'].text(),'')
        self.assertNotEqual(d.property_fields['kin_vis'].text(),'')
