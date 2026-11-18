"""Regression coverage for the six-tab export workflow and solution-dependent analysis."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QScrollArea
from starccm_export_profile import FIELD_CHOICES, REPORT_CHOICES, MEAN_CHOICES, validate_options, save_profile, load_profile
from starccm_export_dialog import StarCcmExportDialog
import test_starccm_fused_export as fused


class AnalysisExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fused.FusedExportTests.setUpClass()
        cls.result=fused.FusedExportTests.result; cls.model=fused.FusedExportTests.model
    def dialog(self):
        d=StarCcmExportDialog(mesh_result=self.result,bundle_model=self.model)
        self.addCleanup(d.deleteLater); return d
    def macro(self, **options):
        from starccm_macro_generator import generate_starccm_java_macro
        return generate_starccm_java_macro('mesh.xyz',self.result,self.model,{}, {},options)
    def test_controls_are_on_the_requested_six_tabs(self):
        d=self.dialog();self.assertEqual(d.tabs.count(),6)
        self.assertEqual(d.tabs.currentIndex(),0)
        def contained(index, control):
            self.assertIsInstance(d.tabs.widget(index), QScrollArea)
            self.assertTrue(d.tabs.widget(index).isAncestorOf(control))
        contained(0,d.chk_group_objects)
        contained(2,d.chk_field_functions)
        contained(2,d.chk_summary)
        for control in (d.chk_scene,d.chk_histograms,d.chk_bad_cells,d.local_quality_text):contained(4,control)
        for control in (*d.report_checkboxes.values(),d.mean_group):contained(5,control)
        self.assertFalse(d.mean_group.isEnabled())
        d.rb_turb_srh.setChecked(True);self.assertTrue(d.mean_group.isEnabled())
        d.rb_turb_rst.setChecked(True);self.assertFalse(d.mean_group.isEnabled())
    def test_selected_fields_reports_and_start_step_roundtrip(self):
        d=self.dialog();d.rb_inter_fuse.setChecked(True);d.rb_eos_iapws.setChecked(True);d.rb_turb_srh.setChecked(True)
        for key,cb in d.field_checkboxes.items():cb.setChecked(key=='z_fraction')
        for cb in d.report_checkboxes.values():cb.setChecked(True)
        for cb in d.mean_checkboxes.values():cb.setChecked(True)
        d.spin_mean_start.setValue(125)
        original=d.read_options()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';save_profile(original,path)
            other=self.dialog();other.apply_options(load_profile(path,2))
            self.assertEqual(other.read_options(),original)
        before=d.read_options()
        for patch in (dict(field_functions=['unknown']),dict(subchannel_reports=['wall','wall']),dict(time_mean_fields=[1]),dict(mean_start_step=True),dict(mean_start_step=0)):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):d.apply_options(dict(before,**patch))
                self.assertEqual(d.read_options(),before)
    def test_local_mesh_audit_runs_in_quality_tab(self):
        d=self.dialog();d.check_export_mesh();text=d.local_quality_text.toPlainText()
        self.assertNotIn('не завершена',text)
        self.assertIn(str(sum((x.shape[0]-1)*(x.shape[1]-1)*self.result.params.nz for x,y in self.result.blocks)),text)
        self.assertIn('min',text)
    def test_height_uses_dimensioned_parameter_and_field_selection(self):
        macro=self.macro(field_functions=['z_fraction'])
        self.assertIn('"MB_ZFraction","${MB_Z} / ${ExportHeight}"',macro)
        self.assertIn('height.getQuantity().setValueAndUnits(length,sim.getUnitsManager().getObject("m"))',macro)
        self.assertNotIn('" [m])"',macro)
        self.assertIn('Arrays.asList("z_fraction")',macro)
        self.assertNotIn('UserFieldFunction alias =',macro)
        self.assertNotIn('getOrCreateFF(sim,"MB_MassBalanceSigned"',macro)
        self.assertIn('coordZFF.setDimensions(Dimensions.Builder().length(1).build())',macro)
        aliases=self.macro(field_functions=['quality'],create_quality_scene=False,create_quality_histograms=False,create_bad_cells=False)
        self.assertIn('UserFieldFunction alias = getOrCreateFF(sim,"MB_CellQuality"',aliases)
        self.assertNotIn('createQualityExtrema(sim, subchannelRegions',aliases)
    def test_analysis_independent_of_visual_sections_and_total_reports(self):
        macro=self.macro(inter_fuse=True,subchannel_reports=list(REPORT_CHOICES),
            selected_subchannels=[2],sub_planes=False,key_planes=False,n_planes=0,
            create_mass_reports=False,axis_probes=False,create_parameters=False)
        execute=macro[:macro.index('    private double[][] boundaryGeometry')]
        self.assertIn('Subchannel_2_Section_Z_0mm',execute)
        self.assertIn('Subchannel_2_Section_Z_50mm',execute)
        self.assertIn('createSubchannelAnalysis(sim,2,sourceParts.get(1)',execute)
        self.assertNotIn('createSubchannelAnalysis(sim,1,',execute)
        self.assertIn('threshold(sim,allRods,wallMask2,"Subchannel_2_RodWalls")',execute)
        self.assertNotIn('"MassFlow_Inlet_Total"',execute)
        # Always use current material fields; no dependence on exported constant properties.
        helpers=macro[macro.index('    private void createSubchannelAnalysis'):macro.index('    private void createTimeMean')]
        for name in ('Density','DynamicViscosity','Pressure','Temperature','BoundaryHeatFlux','WallShearStress'):
            self.assertIn(f'analysisField(sim,"{name}")',helpers)
        self.assertNotIn('${rho}',helpers);self.assertNotIn('${dynvis}',helpers)
        self.assertIn('"massflow",prefix+"BulkTemperature_In"',helpers)
        self.assertIn('prefix+"Darcy_Wall","4 * "',helpers)
        self.assertNotIn('Darcy_PressureDrop',helpers)
        self.assertIn('prefix+"Reynolds_Out"',helpers)
        self.assertIn('"MB_Reynolds_Sub"+number',helpers)
        self.assertIn('${Density} * mag($$Velocity)',helpers)
    def test_time_means_only_generated_for_hybrid_and_energy_enabled(self):
        steady=self.macro(time_mean_fields=list(MEAN_CHOICES))
        execute=steady[:steady.index('    private double[][] boundaryGeometry')]
        self.assertNotIn('createTimeMean(sim,subchannelRegions,',execute)
        unsteady=self.macro(turbulence_model='hybrid_srh',time_mean_fields=list(MEAN_CHOICES),mean_start_step=25,enable_thermal=False)
        execute=unsteady[:unsteady.index('    private double[][] boundaryGeometry')]
        for native in ('Velocity','Pressure','Density','DynamicViscosity'):
            self.assertIn(f'createTimeMean(sim,subchannelRegions,"{native}",25)',execute)
        self.assertNotIn('createTimeMean(sim,subchannelRegions,"Temperature"',execute)
        self.assertIn('createTimeMean(sim,allRods,"WallShearStress",25)',execute)
        self.assertNotIn('createTimeMean(sim,allRods,"BoundaryHeatFlux"',execute)
        self.assertIn('event.setSampleFrequency(1); event.setStartCount(start)',unsteady)
        self.assertIn('Preserve accumulated field statistics',unsteady)
        self.assertIn('ImplicitUnsteadySolver.class',unsteady)
        self.assertNotIn('clearSamples',unsteady)
        iapws=self.macro(turbulence_model='hybrid_srh',use_iapws=True,enable_thermal=False,time_mean_fields=['temperature'])
        self.assertIn('createTimeMean(sim,subchannelRegions,"Temperature",1)',iapws)
    def test_java_report_scopes_and_time_mean_preservation(self):
        import shutil, subprocess
        from starccm_analysis import ANALYSIS_SUPPORT
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
            self.skipTest('JDK compiler unavailable')
        fixture=Path(__file__).parent/'fixtures'/'star_analysis_harness.java'
        source=fixture.read_text().replace('// HELPERS',ANALYSIS_SUPPORT)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'CheckAnalysis.java';path.write_text(source)
            run=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_shared_source_selection_and_dependencies_preserve_choices(self):
        d=self.dialog()
        for checkbox in d.sub_checkboxes:
            self.assertTrue(d.grp_sources.isAncestorOf(checkbox))
            self.assertFalse(d.tabs.isAncestorOf(checkbox))
        d.chk_g_n_planes.setChecked(False);self.assertFalse(d.spin_n_planes.isEnabled())
        d.chk_g_n_planes.setChecked(True);self.assertTrue(d.spin_n_planes.isEnabled())
        d.chk_sub_planes.setChecked(False);self.assertFalse(d.spin_sub_n_planes.isEnabled())
        d.chk_sub_planes.setChecked(True);self.assertTrue(d.spin_sub_n_planes.isEnabled())
        d.report_checkboxes['thermal'].setChecked(True)
        d.chk_thermal.setChecked(False);self.assertFalse(d.report_checkboxes['thermal'].isEnabled())
        self.assertTrue(d.report_checkboxes['thermal'].isChecked())
        d.rb_eos_iapws.setChecked(True);self.assertTrue(d.report_checkboxes['thermal'].isEnabled())
        self.assertFalse(d.chk_thermal.isEnabled())
        for checkbox in d.sub_checkboxes:checkbox.setChecked(False)
        self.assertIn('0/2',d.selection_hint.text())
        self.assertFalse(d.spin_sub_n_planes.isEnabled())
        self.assertTrue(d.chk_sub_n_planes.isChecked())
    def test_display_names_are_clean_but_field_identifiers_stay_stable(self):
        macro=self.macro(subchannel_reports=['hydraulics'],selected_subchannels=[2])
        execute=macro[:macro.index('    private double[][] boundaryGeometry')]
        self.assertIn('cleanManagedDisplayNames(sim);',execute)
        self.assertIn('ff.setPresentationName(displayName(name))',macro)
        self.assertIn('ff.setFunctionName(name)',macro)
        self.assertIn('"MB_ZFraction","${MB_Z} / ${ExportHeight}"',macro)
        self.assertNotIn('createMassFlowReport(sim, "MassFlow_In_Sub2"',execute)
        self.assertIn('createMassFlowReport(sim, "MassFlow_In_Sub1"',execute)
