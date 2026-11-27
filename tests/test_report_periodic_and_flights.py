"""Recorded interface children/local frames and whole-flight time planning."""
import os,re,json,unittest,tempfile,subprocess,shutil
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from copy import deepcopy
import test_compact_star_export as fixture
from starccm_time_schedule import schedule
from starccm_report_support import REPORT_SUPPORT
from starccm_physics_support import PHYSICS_SUPPORT

class ReportPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.model=fixture.CompactExportTests.model;cls.mesh=fixture.CompactExportTests.mesh
    dialog=fixture.CompactExportTests.dialog
    macro=fixture.CompactExportTests.macro
    def test_periodic_totals_use_distinct_interface_sides_and_clear_queries(self):
        for fuse in (False,True):
            d=self.dialog();d.topology_choice.setCurrentIndex(int(fuse));d.boundary_selection_mode.setCurrentIndex(1)
            a,b=('Inlet','Outlet') if fuse else ('Inlet_s1','Outlet_s1')
            d.surface_a.setCurrentIndex(d.surface_a.findData(a));d.surface_b.setCurrentIndex(d.surface_b.findData(b));d.surface_condition.setCurrentIndex(d.surface_condition.findData('fully_developed'));d.add_surface_pair()
            code=self.macro(d)
            self.assertIn(f'periodicReportSide(subchannelRegions.get(0),"{a}","SelectedInterface_1")',code)
            self.assertIn(f'periodicReportSide(subchannelRegions.get(0),"{b}","SelectedInterface_1")',code)
            self.assertIn('"MassFlow_Inlet_Total", reportInlets',code);self.assertIn('"TotalEnthalpy_Outlet", reportOutlets',code)
            self.assertIn('report.getParts().setQuery(null)',code)
            d.report_checkboxes['hydraulics'].setChecked(True);code=self.macro(d)
            if fuse:self.assertIn('threshold(sim,reportInlets,mask1',code)
            else:self.assertIn('reportInlets.get(0),reportOutlets.get(0)',code)
    def test_native_recorded_helpers_and_sync_execute(self):
        java=os.environ.get('TMC_JAVA') or shutil.which('java')
        if not java:self.skipTest('JDK unavailable')
        d=self.dialog();d.topology_choice.setCurrentIndex(1);code=self.macro(d)
        getff=code[code.index('    private UserFieldFunction getOrCreateFF'):code.index('    private void createParam')]
        mesh_only=PHYSICS_SUPPORT[PHYSICS_SUPPORT.index('    private boolean meshOnlyReport'):]
        definition=next(line for line in code.splitlines() if 'String gapVelocityDef1_2=' in line)
        expected='$${Velocity}(@CoordinateSystem("Laboratory.Normal_Gap_Sub1_to_Sub2"))[1]'
        harness=(Path(__file__).parent/'fixtures'/'star_report_setup_harness.java').read_text().replace('// HELPERS',REPORT_SUPPORT+mesh_only+getff).replace('// GAP_DEFINITION',definition).replace('// GAP_ASSERTION','require(gapVelocityDef1_2.equals('+json.dumps(expected)+'),"bad local expression: "+gapVelocityDef1_2);')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'CheckReportSetup.java';p.write_text(harness)
            r=subprocess.run([java,str(p)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_no_coordinate_aliases_and_one_axial_component(self):
        d=self.dialog();d.topology_choice.setCurrentIndex(1);d.report_checkboxes['hydraulics'].setChecked(True)
        code=self.macro(d)
        for name in ('MB_X','MB_Y','MB_Z','MB_AxialVelocity'):self.assertNotIn('getOrCreateFF(sim,"'+name+'",',code);self.assertNotIn('getOrCreateFF(sim, "'+name+'",',code)
        self.assertIn('getFunction("Position").getComponentFunction(0)',code)
        self.assertIn('getOrCreateFF(sim,"Velocity_k","$${Velocity}[2]")',code)
        self.assertIn('frame.getXyPlane().setComponents(nx,ny,0.)',code)
        self.assertIn('"Gap_Sub1_Sub2_MassFluxMean"',code);self.assertIn('"Gap_Sub1_Sub2_AbsMassFluxMean"',code)
    def test_flight_counts_end_time_bound_and_one_cumulative_window(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1);d.runup_passes.setValue(10);d.block_passes.setValue(5);d.blocks_per_run.setValue(5);d.mean_checkboxes['pressure'].setChecked(True)
        values=d.read_options();plan=schedule(values['workflow'],d._surface_catalog,d.read_fluid(),d.yplus_data,d.lz_m,values['time_step'])
        self.assertAlmostEqual(plan['warmup'],10*plan['flight']);self.assertAlmostEqual(plan['block'],5*plan['flight'])
        self.assertGreaterEqual(plan['minimum'],35*plan['flight'])
        code=self.macro(d);self.assertEqual(code.count('createTimeMean(sim,subchannelRegions,"Pressure"'),1)
        self.assertIn(f'configureUnsteadyWorkflow(sim,5,{plan["end"]})',code)
        d.end_time_auto.setChecked(False);d.end_time.setText('0.0001')
        with self.assertRaises(ValueError):d.read_options()
        d.end_time.setValue(plan['minimum']+1);values=d.read_options()
        other=self.dialog();other.apply_options(values);self.assertEqual(other.read_options(),values)

    def test_invalid_schedule_profile_does_not_change_controls(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1)
        before=d.read_options();bad=deepcopy(before)
        bad['workflow']['end_time']=1e-12
        bad['quality_bins']=77
        with self.assertRaises(ValueError):d.apply_options(bad)
        self.assertEqual(d.read_options(),before)
