"""Temporal averaging visibility, component sources and planned sampling window."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
import test_compact_star_export as fixture

class TimeAverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.model=fixture.CompactExportTests.model;cls.mesh=fixture.CompactExportTests.mesh
    dialog=fixture.CompactExportTests.dialog
    macro=fixture.CompactExportTests.macro
    def test_tab_enabled_for_unsteady_rst_or_hybrid_only(self):
        d=self.dialog();self.assertEqual(d.tabs.tabText(4),'5. Среднее по времени');self.assertEqual(d.tabs.tabText(5),'6. Качество сетки')
        self.assertFalse(d.tabs.isTabEnabled(4));d.simulation_mode.setCurrentIndex(1);self.assertTrue(d.tabs.isTabEnabled(4))
        d.turbulence_choice.setCurrentIndex(1);self.assertTrue(d.tabs.isTabEnabled(4));d.simulation_mode.setCurrentIndex(0);self.assertFalse(d.tabs.isTabEnabled(4))
    def test_component_fields_have_units_and_distinct_sources(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1)
        for base in ('velocity','wall_shear'):
            for axis in ('i','j','k'):d.mean_checkboxes[base+'_'+axis].setChecked(True)
        values=d.read_options();self.assertNotIn('velocity',values['time_mean_fields']);self.assertNotIn('wall_shear',values['time_mean_fields'])
        code=self.macro(d)
        for source,parts in (('Velocity','subchannelRegions'),('WallShearStress','allRods')):
            for index,axis in enumerate(('i','j','k')):
                self.assertIn(f'"$${{{source}}}[{index}]"',code)
                self.assertIn(f'createTimeMean(sim,{parts},"{source}_{axis}"',code)
        self.assertIn('м/с',d.mean_checkboxes['velocity_i'].text());self.assertIn('Па',d.mean_checkboxes['wall_shear_i'].text())
        self.assertIn('Дж/кг',d.mean_checkboxes['enthalpy'].text());self.assertIn('Вт/м²',d.mean_checkboxes['wall_heat_flux'].text())
    def test_energy_and_iapws_gates_preserve_selected_fields(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1);d.show();d.tabs.setCurrentIndex(4);self.app.processEvents()
        self.assertFalse(d.mean_checkboxes['density'].isVisible());self.assertFalse(d.mean_checkboxes['viscosity'].isVisible())
        d.property_choice.setCurrentIndex(1);self.assertTrue(d.mean_checkboxes['density'].isVisible())
        for key in ('density','viscosity','enthalpy','temperature','wall_heat_flux'):d.mean_checkboxes[key].setChecked(True)
        d.property_choice.setCurrentIndex(0);d.chk_thermal.setChecked(False)
        code=self.macro(d)
        for field in ('Density','DynamicViscosity','TotalEnthalpy','Temperature','BoundaryHeatFlux'):
            self.assertNotIn(f'createTimeMean(sim,subchannelRegions,"{field}"',code)
            self.assertNotIn(f'createTimeMean(sim,allRods,"{field}"',code)
        self.assertTrue(d.mean_checkboxes['density'].isChecked());d.close()
    def test_start_after_runup_and_collection_window(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1);d.warmup_duration.setValue(.2);d.field_time_step.setValue(.01);d.block_duration.setValue(.3);d.blocks_per_run.setValue(2)
        d.mean_checkboxes['pressure'].setChecked(True);values=d.read_options();self.assertEqual(values['mean_start_step'],21)
        self.assertTrue(values['workflow']['mean_start_auto']);self.assertIn('createTimeMean(sim,subchannelRegions,"Pressure",21)',self.macro(d))
        self.assertIn('configureUnsteadyWorkflow(sim,5,0.8)',self.macro(d))
        d.mean_start_auto.setChecked(False);self.assertFalse(d.manual_mean_start_row.isHidden());d.spin_mean_start.setValue(7);self.assertEqual(d.read_options()['mean_start_step'],7)
        other=self.dialog();other.apply_options(d.read_options());self.assertEqual(other.read_options(),d.read_options())
    def test_legacy_vector_profile_expands_to_components_and_keeps_manual_start(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1);values=d.read_options();values['workflow'].pop('mean_start_auto');values.update(time_mean_fields=['velocity','wall_shear'],mean_start_step=125)
        d.apply_options(values);self.assertFalse(d.mean_start_auto.isChecked());self.assertEqual(d.read_options()['mean_start_step'],125)
        self.assertEqual(set(d.read_options()['time_mean_fields']),{base+'_'+axis for base in ('velocity','wall_shear') for axis in ('i','j','k')})
