import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from dataclasses import replace
import sys, unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from starccm_export_geometry import export_geometry, surface_signature, plane_positions
from starccm_macro_generator import generate_starccm_java_macro
from starccm_export_dialog import StarCcmExportDialog

class FusedExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.model=BundleModel()
        interiors=[sid for sid,s in cls.model.subchannels.items() if s.sub_type=='interior']
        a=interiors[0]
        b=next(sid for sid in interiors[1:] if len(set(cls.model.subchannels[a].rod_ids)&set(cls.model.subchannels[sid].rod_ids))==2)
        cls.ids=[a,b]
        cls.model.selected_subchannels=set(cls.ids)
        cls.result=build_mesh_from_bundle_model(cls.model,MeshParams(ni=12,nj=20,nz=2))
    def macro(self, **opts):
        return generate_starccm_java_macro('mesh.xyz',self.result,self.model,{}, {},dict(inter_fuse=True,**opts))
    def test_source_order_and_fused_geometry_do_not_use_mutable_selection(self):
        signatures,domains=export_geometry(self.result,self.model)
        self.assertEqual([d['source_id'] for d in domains],list(dict.fromkeys(row[0] for row in self.result.instances_map)))
        # Four exterior gaps remain after fusing two adjacent triangles. Classify
        # their analytic midpoint/area from rod centers, independent of mesh rows.
        edges={}
        for sid in self.ids:
            ids=self.model.subchannels[sid].rod_ids
            for a,b in zip(ids,ids[1:]+ids[:1]):edges[tuple(sorted((a,b)))]=edges.get(tuple(sorted((a,b))),0)+1
        external=[pair for pair,n in edges.items() if n==1]
        self.assertEqual(len(external),4)
        for a,b in external:
            ra,rb=self.model.rods[a],self.model.rods[b]
            ca=np.array([ra.x,ra.y])*1e-3;cb=np.array([rb.x,rb.y])*1e-3
            v=(cb-ca)/np.linalg.norm(cb-ca)
            p=ca+v*ra.diameter*.5e-3;q=cb-v*rb.diameter*.5e-3
            area=np.linalg.norm(q-p)*self.result.params.z_len*1e6;center=(p+q)/2
            matches=[row for row in signatures if abs(row[2]-area)<1e-5 and np.linalg.norm(np.array(row[3:])-center)<1e-8]
            self.assertTrue(matches)
            self.assertTrue(all(row[0]==0 for row in matches),matches)
        macro=self.macro()
        self.assertNotIn('k < 3',macro)
        self.assertNotIn('laterals.sort',macro)
        self.assertIn('classifyBoundary(bd.area',macro)
        self.assertIn('Неизвестная боковая поверхность',macro)
    def test_fused_sections_are_clipped_to_both_original_domains(self):
        macro=self.macro()
        for number in (1,2):
            self.assertIn(f'Subchannel_{number}_Domain',macro)
            self.assertIn(f'SubchannelMask_{number}',macro)
            self.assertIn(f'sourceParts.get({number-1})',macro)
            self.assertIn(f'Probe_Axis_Subchannel_{number}',macro)
            self.assertIn(f'MassFlow_In_Sub{number}',macro)
            self.assertIn(f'MassFlow_Out_Sub{number}',macro)
        self.assertNotIn('TVS_Assembly_Section',macro)
        self.assertNotIn('if (2 <= subchannelRegions.size())',macro)
        self.assertEqual(macro.count('createThresholdPart('),2)
    def test_source_masks_recover_original_cells_after_fuse(self):
        _,domains=export_geometry(self.result,self.model)
        centers=[]
        owners=[]
        for idx,(x,y) in enumerate(self.result.blocks):
            points=np.stack((x,y),axis=-1)
            cell_centers=(points[:-1,:-1]+points[1:,:-1]+points[1:,1:]+points[:-1,1:])/4
            centers.extend(cell_centers.reshape(-1,2))
            owners.extend([self.result.instances_map[idx][0]]*cell_centers.shape[0]*cell_centers.shape[1])
        centers=np.asarray(centers)
        for domain in domains:
            triangle=domain['triangle']
            inside=np.ones(len(centers),dtype=bool)
            for a,b in zip(triangle,np.roll(triangle,-1,axis=0)):
                d=b-a;v=centers-a
                inside &= d[0]*v[:,1]-d[1]*v[:,0]>=-1e-16
            np.testing.assert_array_equal(inside,np.asarray(owners)==domain['source_id'])

    def test_planes_do_not_duplicate_key_and_regular_positions(self):
        self.assertEqual(len(plane_positions(11,True)),11)
        self.assertEqual(len(plane_positions(4,True)),5)
        macro=self.macro()
        # Eleven global and eleven per source, not 14 per group.
        self.assertEqual(macro.count('createPlaneSection(sim,'),33)
        macro=self.macro(selected_subchannels=[2],create_mass_reports=False)
        self.assertNotIn('Subchannel_1_Section',macro)
        self.assertNotIn('Probe_Axis_Subchannel_1',macro)
        self.assertIn('Probe_Axis_Subchannel_2',macro)
    def test_mass_and_energy_reports_are_independent_of_monitor_failures(self):
        macro=self.macro()
        for name in ('Imbalance_MassFlow','Heat_Flux_Rods_Total','Heat_Flux_Walls_Total',
                     'Energy_Flow_Inlet_Total','Energy_Flow_Outlet_Total','Imbalance_Energy'):
            self.assertIn(f'"{name}"',macro)
        self.assertIn('MassFlow_Inlet_TotalReport} + ${MassFlow_Outlet_TotalReport',macro)
        self.assertIn('report.createMonitor()',macro)
        self.assertNotIn('createMonitors(',macro)
        self.assertIn('[!] Монитор',macro)
        self.assertIn('[!] Отчет',macro)
        self.assertNotIn('ПОЛНОСТЬЮ НАСТРОЕНА И ГОТОВА К РАСЧЕТУ',macro)
        self.assertNotIn('createHeatReport(sim, "Heat_Flux_Rods_Total"',self.macro(enable_thermal=False))
    def test_fused_sector_choice_is_rejected_and_disabled_in_ui(self):
        with self.assertRaisesRegex(ValueError,'60'):
            self.macro(rod_wall_mode='sectors_60')
        dialog=StarCcmExportDialog(mesh_result=self.result,bundle_model=self.model)
        try:
            dialog.rb_wall_60.setChecked(True)
            dialog.rb_inter_fuse.setChecked(True)
            self.assertFalse(dialog.rb_wall_60.isEnabled())
            self.assertFalse(dialog.rb_wall_60.isChecked())
            self.assertTrue(dialog.rb_wall_by_rod.isChecked())
            dialog.rb_inter_intf.setChecked(True)
            self.assertTrue(dialog.rb_wall_60.isEnabled())
        finally:dialog.deleteLater()
    def test_nonfused_mode_does_not_create_thresholds(self):
        macro=generate_starccm_java_macro('mesh.xyz',self.result,self.model,{}, {},{})
        self.assertNotIn('createThresholdPart(',macro)
        self.assertIn('for (Region region : subchannelRegions)',macro)
        with self.assertRaisesRegex(ValueError,'геометрия'):
            generate_starccm_java_macro('mesh.xyz',self.result,None,{}, {},{'inter_fuse':True})
    def test_java_syntax_and_actual_classifier_execution(self):
        import shutil, subprocess, tempfile
        java=shutil.which('java')
        if java is None:
            self.skipTest('Java unavailable: geometry Python tests still run')
        modules=subprocess.run([java,'--list-modules'],capture_output=True,text=True)
        if 'jdk.compiler' not in modules.stdout:
            self.skipTest('JDK compiler module unavailable')
        macro=self.macro()
        start=macro.index('    private int classifyBoundary')
        end=macro.index('    private void registerReport',start)
        method=macro[start:end].replace('private int classifyBoundary','private static int classifyBoundary')
        reports=macro[end:macro.index('    private void createHeatReport',end)]
        signatures,domains=export_geometry(self.result,self.model)
        rows=',\n'.join('{'+','.join(format(float(v),'.16e') for v in row)+'}' for row in signatures)
        # Execute the exact emitted classifier, including the fourth fused gap.
        harness='''import java.nio.file.*;
import java.util.*;
import javax.tools.*;
import com.sun.source.util.JavacTask;
class Check {
METHOD
REPORT_METHODS
static class NamedObject {}
static class Parts { void setObjects(List<? extends NamedObject> parts) {} }
static class Report extends NamedObject {
    String name;
    void setPresentationName(String s) { name=s; }
    String getPresentationName() { return name; }
    Parts getParts() { return new Parts(); }
    void createMonitor() { throw new IllegalStateException("simulated monitor failure"); }
}
static class MassFlowReport extends Report {}
static class ExpressionReport extends Report { void setDefinition(String s) {} }
static class ReportManager {
    <T extends Report> T createReport(Class<T> type) throws Exception { return type.getDeclaredConstructor().newInstance(); }
}
static class Simulation {
    List<String> errors=new ArrayList<>();
    void println(String s) { errors.add(s); }
    ReportManager getReportManager() { return new ReportManager(); }
}
public static void main(String[] args) throws Exception {
    double[][] rows = new double[][] { ROWS };
    for (double[] row : rows) {
        int expected = row[0] == 0 ? 0 : 1 + (int)row[1];
        if (classifyBoundary(row[2],row[3],row[4],rows) != expected) throw new AssertionError("wrong surface");
    }
    if (classifyBoundary(1e10,100,100,rows) != -1) throw new AssertionError("unknown surface");
    Check check=new Check(); Simulation sim=new Simulation(); int[] counts={0,0};
    check.createMassFlowReport(sim,"MassFlow_Inlet_Total",List.of(),counts);
    check.createMassFlowReport(sim,"MassFlow_Outlet_Total",List.of(),counts);
    check.createExpressionReport(sim,"Imbalance_MassFlow","0",counts);
    if (counts[0]!=3 || counts[1]!=0 || sim.errors.size()!=3) throw new AssertionError("monitor failure suppressed reports");
    JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
    DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
    try (StandardJavaFileManager fm = compiler.getStandardFileManager(diagnostics,null,null)) {
        JavacTask task = (JavacTask)compiler.getTask(null,fm,diagnostics,List.of("-proc:none"),null,fm.getJavaFileObjects(args[0]));
        task.parse();
        for (Diagnostic<?> d : diagnostics.getDiagnostics())
            if (d.getKind() == Diagnostic.Kind.ERROR) throw new AssertionError(d.toString());
    }
}}
'''.replace('REPORT_METHODS',reports).replace('METHOD',method).replace('ROWS',rows)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'setup_starccm_subchannels.java';source.write_text(macro,encoding='utf-8')
            check=Path(tmp)/'Check.java';check.write_text(harness,encoding='utf-8')
            result=subprocess.run([java,str(check),str(source)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
