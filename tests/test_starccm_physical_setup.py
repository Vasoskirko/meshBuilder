"""Physical-value binding and initialization must precede solution report evaluation."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys, unittest, tempfile, subprocess, shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_starccm_fused_export as fused
from starccm_macro_generator import generate_starccm_java_macro
from starccm_physics_support import PHYSICS_SUPPORT

class PhysicalSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fused.FusedExportTests.setUpClass()
    def macro(self, **opts):
        return generate_starccm_java_macro('mesh.xyz',fused.FusedExportTests.result,fused.FusedExportTests.model,{}, {},opts)
    def test_configuration_and_initialization_precede_reports_even_without_optional_parameters(self):
        code=self.macro(create_parameters=False)
        execute=code[:code.index('    private double[][] boundaryGeometry')]
        order=[execute.index(x) for x in ('setupPhysics = phys','createParam(sim, gpm, null, "rho"',
            'physicalValuesConfigured = configurePhysicalValues','initializeFirstSolution(sim,reuse,true',
            'createMassFlowReport(sim, "MassFlow_Inlet_Total"','writeSummary(sim,subchannelRegions')]
        self.assertEqual(order,sorted(order))
        self.assertIn('"P_init",0.0,"Pa"',execute)
        self.assertIn('"T_init",0.0,"K"',execute)
        self.assertIn('"${T_ref}"',execute)
        self.assertIn('createParam(sim, gpm, null, "U_b"',execute);self.assertNotIn('U_init',execute)
        self.assertIn('initializeFirstSolution(sim,reuse,false',self.macro(initialize_solution=False))
        self.assertIn('sim.getSolution().isInitialized()',code)
        self.assertLess(code.index('String reason=auditDeferral(name,evaluateSolution,initialized,progressed)'),code.index('double value=auditReportValue(sim,report'))
        self.assertIn('solution not initialized',code)
    def test_ub_is_the_only_initial_velocity_parameter(self):
        from starccm_workflow import validate_workflow
        for mode in ('theory','zero','seed'):
            wf=validate_workflow(dict(initial_velocity=mode,velocity_seed=mode=='seed'))
            code=self.macro(workflow=wf,create_parameters=False)
            self.assertNotIn('createParam(sim,gpm,null,"U_init"',code);self.assertNotIn('${U_init}',code)
            if mode!='zero':self.assertIn('"U_b", 0.0, "m/s"',code)
            if mode=='seed':self.assertIn('initialVelocity.getMethod(FunctionVectorProfileMethod.class).setFieldFunction(seed)',code)
            if mode=='zero':
                self.assertIn('false,true,true,true,true);',code)
                wf['boundary_pairs']=[dict(first='Inlet_s1',second='Outlet_s1',kind='fully_developed',mass_flow=1.,mass_flow_auto=True)]
                with_flow=self.macro(workflow=wf,create_parameters=False)
                self.assertIn('"${rhoW_in}/${rho}"',with_flow);self.assertIn('setDefinition("${G_subchannel}*${S_in_Sub1}/${S_in}")',with_flow)

    def test_initialization_checkbox_profile_roundtrip(self):
        from starccm_export_dialog import StarCcmExportDialog
        d=StarCcmExportDialog(mesh_result=fused.FusedExportTests.result)
        self.addCleanup(d.deleteLater)
        self.assertFalse(d.chk_initialize.isChecked())
        options=d.read_options();options['initialize_solution']=False;d.apply_options(options)
        self.assertFalse(d.read_options()['initialize_solution'])
        self.assertTrue(d.summary_tab.isAncestorOf(d.chk_initialize))
    def test_java_physical_bindings_iapws_and_no_reinitialization(self):
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
            self.skipTest('JDK compiler unavailable')
        fixture=Path(__file__).parent/'fixtures'/'star_physics_harness.java'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'CheckPhysics.java';path.write_text(fixture.read_text().replace('// HELPERS',PHYSICS_SUPPORT))
            run=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
