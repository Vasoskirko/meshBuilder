"""Offscreen regressions for the real seven-tab dialog and its export adapter."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model,export_subchannel_plot3d
from starccm_export_dialog import StarCcmExportDialog
from starccm_macro_generator import generate_starccm_java_macro
from starccm_export_profile import save_profile,load_profile,validate_options
from starccm_workflow import validate_workflow,estimate_plot3d_bytes
from starccm_tmc_export import write_tmc_bundle

class UnifiedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.model=BundleModel(pitch=11.64);cls.model.selected_subchannels={18,22}
        cls.mesh=build_mesh_from_bundle_model(cls.model,MeshParams(ni=45,nj=20,nz=2,z_len=.3))
    def dialog(self):
        d=StarCcmExportDialog(mesh_result=self.mesh,bundle_model=self.model,
            fluid_props=dict(density=747.339,dyn_vis=9.27175e-5,cp=5225.098,**{'lambda':.57532},t_ref_c=290.,p_ref_mpa=16.2))
        self.addCleanup(d.deleteLater);return d
    def macro(self,d):return generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,d.read_options())
    def test_tabs_and_quality_off_do_not_create_quality_objects(self):
        d=self.dialog();self.assertEqual(d.tabs.count(),8);self.assertFalse(d.quality_enabled.isChecked())
        self.assertFalse(d.chk_initialize.isEnabled());self.assertFalse(d.chk_initialize.isChecked())
        code=self.macro(d);execute=code.split('private void createParam')[0]
        self.assertNotIn('createQualityHistogram(sim, subchannelRegions',execute)
        self.assertNotIn('createBadCells(sim, subchannelRegions',execute)
        self.assertNotIn('countReport(sim,"Quality_TotalCellCount"',execute)
        d.quality_enabled.setChecked(True);d.quality_thresholds['CellQuality'].setText('0,02')
        code=self.macro(d);self.assertIn('"<= 0.02"',code);self.assertIn('Quality_Histogram_CellQuality__bad_le_0.02',code)
    def test_properties_initial_values_and_decimal_separators_reach_macro(self):
        d=self.dialog();d.fluid_fields['dyn_vis'].setText('9,1e-5');d.initial_pressure.setText('123,5');d.initial_velocity.setCurrentIndex(0)
        d.initial_temperature.setText('560,25');code=self.macro(d)
        self.assertIn('"P_init",123.5',code);self.assertIn('"T_init",560.25',code)
        self.assertNotIn('createParam(sim,gpm,null,"U_init"',code);self.assertNotIn('${U_init}',code);self.assertIn('zeroVelocity ? "[0, 0, 0]" : "[0, 0, ${U_b}]"',code)
        d.initial_pressure.setText('-17000000')
        with self.assertRaises(ValueError):self.macro(d)
    def test_profile_roundtrip_nested_settings_and_old_profile_migration(self):
        d=self.dialog();d.fluid_fields['density'].setText('730,5');d.quality_enabled.setChecked(True)
        d.initial_velocity.setCurrentIndex(0);d.warmup_duration.setValue(.6)
        values=d.read_options()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json';save_profile(values,path)
            other=self.dialog();other.apply_options(load_profile(path,2));self.assertEqual(other.read_options(),values)
        old=deepcopy(values);old.pop('workflow');migrated=validate_options(old,2)
        self.assertTrue(migrated['workflow']['quality_enabled'])
        for bad in ({'unknown':1},{'inner_iterations':True},{'fluid':{'density':float('nan')}},{'quality_thresholds':{}}):
            with self.assertRaises(ValueError):validate_workflow(bad)
    def test_interfaces_restrict_physical_rod_grouping(self):
        d=self.dialog();d.rb_inter_fuse.setChecked(True);d.rb_wall_by_rod.setChecked(True)
        d.rb_inter_intf.setChecked(True)
        self.assertTrue(d.rb_wall_60.isChecked());self.assertFalse(d.rb_wall_by_rod.isEnabled())
        self.assertTrue(d.rb_wall_rod.isEnabled());d.rb_wall_rod.setChecked(True)
        validate_options(d.read_options(),2)
    def test_unsteady_parameter_and_flat_folders(self):
        d=self.dialog();d.rb_turb_srh.setChecked(True);d.inner_iterations.setValue(7)
        code=self.macro(d)
        self.assertIn('${timeStep}',code);self.assertIn('configureUnsteadyWorkflow(sim,7,0.9)',code)
        self.assertIn('getTimeDiscretizationOption().setSelected(TimeDiscretizationOption.Type.SECOND_ORDER)',code);self.assertIn('getSchemeOption().setSelected(ImplicitSchemeOption.Type.SIMPLEC)',code)
        self.assertIn('"Maximum Steps"',code);self.assertNotIn('nativeGroupObjects(roots,"meshBuilder_"',code)
    def test_size_estimate_matches_current_ascii_writer_without_3d_allocation(self):
        low,high=estimate_plot3d_bytes(self.mesh)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'mesh.xyz';export_subchannel_plot3d(self.mesh,file)
            self.assertLessEqual(low,file.stat().st_size);self.assertGreaterEqual(high,file.stat().st_size)
    def test_seed_and_gap_table(self):
        d=self.dialog();d.seed_functions.setChecked(True);code=self.macro(d)
        self.assertIn('"pi",Math.PI',code);self.assertIn('"VelocitySeed"',code)
        self.assertIn('sin(7*${thetaZ}+1.9)',code);self.assertEqual(d.gap_table.rowCount(),1)
        self.assertEqual(d.gap_table.item(0,0).text(),'Gap_Sub1_Sub2')
    def test_tdc_bundle_uses_shared_physics_time_and_new_names(self):
        d=self.dialog();d.rb_inter_fuse.setChecked(True);d.rb_turb_srh.setChecked(True);d.tdc_enabled.setChecked(True);d.tdc_equivalence.setChecked(True);d.heat_enabled.setChecked(True)
        d.field_time_step.setText('2,5e-5');d.warmup_duration.setValue(.6);d.block_duration.setValue(.3)
        values=d.read_options();self.assertEqual(values['tmc_settings']['rho'],747.339)
        with tempfile.TemporaryDirectory() as tmp,patch('mesh_subchannel.export_subchannel_plot3d',side_effect=lambda r,p,**kw:Path(p).write_text('XYZ')):
            paths=write_tmc_bundle(tmp,'mesh.xyz',self.mesh,self.model,values['tmc_settings'],lambda *a:None,unified_options=values)
            self.assertEqual(paths[2].name,'TDC_Hybrid.java');control=paths[2].read_text()
            self.assertIn('public class TDC_Hybrid',control);self.assertIn('case 1: phase(false,',control)
            self.assertIn('${timeStep}',control);self.assertIn('"Maximum Physical Time"',control)
            self.assertNotIn('TMC_',control);self.assertIn('TDC_START.txt',[p.name for p in paths])
    def test_generated_tdc_compiles_against_explicit_api_contracts(self):
        import shutil,subprocess
        import test_tmc_hybrid
        command,java=test_tmc_hybrid.compiler()
        if command is None:self.skipTest('Java compiler unavailable; not a Siemens SDK compile')
        d=self.dialog();d.rb_inter_fuse.setChecked(True);d.rb_turb_srh.setChecked(True)
        d.tdc_enabled.setChecked(True);d.tdc_equivalence.setChecked(True);d.heat_enabled.setChecked(True)
        values=d.read_options()
        with tempfile.TemporaryDirectory() as tmp,patch('mesh_subchannel.export_subchannel_plot3d',side_effect=lambda r,p,**kw:Path(p).write_text('XYZ')):
            root=Path(tmp);paths=write_tmc_bundle(root,'mesh.xyz',self.mesh,self.model,values['tmc_settings'],lambda *a:None,unified_options=values)
            test_tmc_hybrid.write_stubs(root)
            macro=root/'macro';macro.mkdir();shutil.copy(paths[2],macro/paths[2].name)
            run=subprocess.run(command+[str(root/'classes')]+[str(p) for p in root.rglob('*.java') if p!=paths[1] and p!=paths[2]],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertNotIn('TMC_',paths[5].read_text())
    def test_recorded_solver_api_executes_and_invalid_settings_fail(self):
        import shutil,subprocess
        from starccm_unified_support import UNIFIED_SUPPORT
        java=shutil.which('java') or os.environ.get('TMC_JAVA')
        if not java:self.skipTest('Java runtime unavailable')
        if 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:self.skipTest('JDK compiler unavailable')
        fixture=Path(__file__).parent/'fixtures'/'star_workflow_harness.java'
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'CheckWorkflow.java';file.write_text(fixture.read_text().replace('// HELPERS',UNIFIED_SUPPORT))
            run=subprocess.run([java,str(file)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    def test_inactive_drafts_do_not_block_other_export_modes(self):
        d=self.dialog();d.quality_enabled.setChecked(True)
        d.quality_thresholds['CellQuality'].setText('invalid')
        with self.assertRaises(ValueError):d.read_options()
        d.quality_enabled.setChecked(False)
        self.assertFalse(d.read_options()['create_quality_histograms'])
        d.rb_turb_srh.setChecked(True);d.field_time_step.setText('invalid');d.block_duration.setText('invalid')
        with self.assertRaises(ValueError):d.read_options()
        d.rb_turb_rst.setChecked(True);self.assertEqual(d.read_options()['turbulence_model'],'rst')

    def test_gap_reports_have_oriented_velocity_temperature_and_enthalpy(self):
        d=self.dialog();d.rb_inter_fuse.setChecked(True);d.chk_gap_sections.setChecked(True)
        code=self.macro(d)
        for name in ('Gap_Sub1_Sub2_NormalVelocity','Gap_Sub1_Sub2_TemperatureMean','Gap_Sub1_Sub2_EnthalpyFlow'):
            self.assertIn(name,code)
        self.assertIn('gapVelocity1_2.setDimensions',code)
        self.assertIn('scalarReport(sim,"surface","Gap_Sub1_Sub2_EnthalpyFlow"',code)
