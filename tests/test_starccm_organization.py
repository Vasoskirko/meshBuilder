"""Purpose-based organization and safe post-solve audit regressions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys, unittest, tempfile, shutil, subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_starccm_fused_export as fused
from starccm_export_dialog import StarCcmExportDialog
from starccm_macro_generator import generate_starccm_java_macro
from starccm_export_profile import load_profile,save_profile,validate_options
from starccm_audit_support import AUDIT_SUPPORT
from starccm_physics_support import PHYSICS_SUPPORT

class OrganizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fused.FusedExportTests.setUpClass()
    def dialog(self):
        d=StarCcmExportDialog(mesh_result=fused.FusedExportTests.result)
        self.addCleanup(d.deleteLater);return d
    def macro(self,**options):
        return generate_starccm_java_macro('mesh.xyz',fused.FusedExportTests.result,fused.FusedExportTests.model,{}, {},options)
    def test_gravity_all_axes_and_profile_roundtrip(self):
        d=self.dialog();self.assertFalse(d.combo_gravity.isEnabled())
        d.chk_gravity.setChecked(True);self.assertTrue(d.combo_gravity.isEnabled())
        for axis,vector in [('-X','-9.81,0.0,0.0'),('+X','9.81,0.0,0.0'),('-Y','0.0,-9.81,0.0'),('+Y','0.0,9.81,0.0'),('-Z','0.0,0.0,-9.81'),('+Z','0.0,0.0,9.81')]:
            with self.subTest(axis=axis):
                code=self.macro(enable_gravity=True,gravity_axis=axis)
                self.assertIn('get(Gravity.class).setConstant(new double[] {'+vector+'})',code)
        d.combo_gravity.setCurrentText('+Y');d.chk_evaluate_solution.setChecked(True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';save_profile(d.read_options(),path)
            other=self.dialog();other.apply_options(load_profile(path,2));self.assertEqual(other.read_options(),d.read_options())
        with self.assertRaises(ValueError):validate_options(dict(d.read_options(),gravity_axis='invalid'))
        self.assertNotIn('get(Gravity.class).setConstant',self.macro(enable_gravity=False))
    def test_static_report_monitors_are_not_created(self):
        code=self.macro()
        registry=code[code.index('    private void registerReport'):code.index('    private void createMassFlowReport')]
        self.assertLess(registry.index('if (meshOnlyReport(report.getPresentationName())) return'),registry.index('report.createMonitor()'))
        self.assertIn('counts[0]++',registry)
        self.assertIn('counts[1]++',registry)
        self.assertIn('"LegacyStatic"',code)
        self.assertNotIn('removeObjects(',code)
    def test_explicit_physical_evaluation_off_by_default_and_gated_after_solve(self):
        code=self.macro();self.assertIn('writeSummary(sim,subchannelRegions,exportFingerprint,expectedCells,false)',code)
        self.assertIn('writeSummary(sim,subchannelRegions,exportFingerprint,expectedCells,true)',self.macro(evaluate_solution_reports=True))
        self.assertIn('getCurrentIteration()>0',code)
        self.assertIn('new ArrayList<Report>(sim.getReportManager().getObjects())',code)
        d=self.dialog();self.assertFalse(d.chk_evaluate_solution.isChecked())
        d.chk_summary.setChecked(False);self.assertFalse(d.chk_evaluate_solution.isEnabled())
    def test_java_zero_mass_average_and_nonfinite_dependencies_never_reach_native_expressions(self):
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
            self.skipTest('JDK compiler unavailable')
        fixture=Path(__file__).parent/'fixtures'/'star_audit_harness.java'
        policy=PHYSICS_SUPPORT[PHYSICS_SUPPORT.index('    private boolean meshOnlyReport'):]
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'CheckAudit.java';source.write_text(fixture.read_text().replace('// HELPERS',AUDIT_SUPPORT+policy))
            run=subprocess.run([java,str(source)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
