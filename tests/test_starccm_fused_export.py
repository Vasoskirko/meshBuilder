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
        self.assertEqual(macro.count('= threshold(sim, subchannelRegions, mask'),2)
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
        self.assertNotIn('= threshold(sim, subchannelRegions, mask',macro)
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
        macro=self.macro(subchannel_reports=['geometry','hydraulics','wall','thermal'],
            turbulence_model='hybrid_srh',time_mean_fields=['velocity','pressure','temperature','density','viscosity'])
        start=macro.index('    private int classifyBoundary')
        end=macro.index('    private void registerReport',start)
        method=macro[start:end].replace('private int classifyBoundary','private static int classifyBoundary')
        reports=macro[end:macro.index('    private void createHeatReport',end)]
        from starccm_physics_support import PHYSICS_SUPPORT
        reports += PHYSICS_SUPPORT[PHYSICS_SUPPORT.index('    private boolean meshOnlyReport'):]
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
<T extends Report> T ownedReport(Simulation sim,String name,Class<T> type) throws Exception {
    return sim.getReportManager().createReport(type);
}
void own(Simulation sim,Object object) {}
void warn(Simulation sim,String message) { sim.println(message); }
static class ReportMonitor { Report getReport() { return null; } }
static class MonitorManager { <T> List<T> getObjectsOf(Class<T> type) { return List.of(); } }

static class NamedObject {}
static class Parts { void setObjects(List<? extends NamedObject> parts) {} }
static class Report extends NamedObject {
    String name;
    void setPresentationName(String s) { name=s; }
    String getPresentationName() { return name; }
    Parts getParts() { return new Parts(); }
    ReportMonitor createMonitor() { throw new IllegalStateException("simulated monitor failure"); }
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
    MonitorManager getMonitorManager() { return new MonitorManager(); }
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
    check.createMassFlowReport(sim,"Quality_Min_Test",List.of(),counts);
    check.createExpressionReport(sim,"Sub1_Area_In","1",counts);
    if (counts[0]!=5 || counts[1]!=0 || sim.errors.size()!=3) throw new AssertionError("monitor failure suppressed reports");
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
    def test_compact_names_contain_physical_height_and_stay_unique(self):
        from starccm_export_geometry import plane_label
        self.assertEqual(plane_label('Section_Global',.5,.05),'Section_Global_Z_25mm')
        for height in (1e-6,.05,1000):
            positions=plane_positions(100,True)
            names=[plane_label('Section',pos,height) for pos in positions]
            self.assertEqual(len(names),len(set(names)))
            self.assertTrue(all('000000000000' not in name for name in names))
        macro=self.macro()
        self.assertIn('"Section_Global_Z_25mm"',macro)
        self.assertIn('"Subchannel_1_Section_Z_0mm"',macro)
        self.assertNotIn('Section_Global_Z_0.500000000000',macro)
        # Names are rounded, but geometry coordinates retain scientific precision.
        self.assertIn('lz * 5.0000000000000000e-01',macro)
    def test_gap_plane_uses_original_common_edge_and_one_source_side(self):
        from starccm_export_geometry import shared_gap_sections
        _,domains=export_geometry(self.result,self.model)
        gaps=shared_gap_sections(domains)
        self.assertEqual(len(gaps),1)
        gap=gaps[0]
        self.assertEqual((gap['a'],gap['b']),(1,2))
        self.assertAlmostEqual(np.linalg.norm(gap['normal']),1)
        common=[p for p in domains[0]['triangle'] if any(np.allclose(p,q,rtol=0,atol=1e-12) for q in domains[1]['triangle'])]
        self.assertAlmostEqual(np.dot(common[1]-common[0],gap['normal']),0,places=12)
        self.assertGreater(np.dot(domains[1]['center']-domains[0]['center'],gap['normal']),0)
        macro=self.macro()
        self.assertIn('createOrientedPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Gap_Sub1_Sub2"',macro)
        self.assertNotIn('"Gap_Sub1_Sub2"',self.macro(gap_sections=False))
    def test_histograms_and_scenes_are_configured_with_real_fields_and_parts(self):
        macro=self.macro(quality_bins=37)
        for metric, suffix, criterion in (
                ('CellQuality','lt_1e-5','< 1e-5'),
                ('FaceValidity','lt_1','< 1'),
                ('VolumeChange','le_0.01','<= 0.01'),
                ('SkewnessAngle','gt_85deg','> 85 deg')):
            self.assertIn(f'"Quality_Histogram_{metric}__bad_{suffix}", "{criterion}", 37',macro)
            self.assertIn(f'"Quality_{metric}"',macro)
        self.assertIn('WeightingMode.FREQUENCY',macro)
        self.assertIn('axis.hasBinningDescriptor().setNumberOfBins(bins)',macro)
        self.assertIn('scalar.getInputParts().setObjects(surfaces)',macro)
        self.assertIn('scalar.getScalarDisplayQuantity().setFieldFunction(metric)',macro)
        self.assertIn('scalar.setFillMode(ScalarFillMode.NATIVE)',macro)
        self.assertIn('minimum.getParts().setObjects(regions)',macro)
        self.assertNotIn('createScalarScene(',macro)
        self.assertIn('if (surfaces.isEmpty()) throw',macro)
        self.assertIn('[!] Качество CellQuality',macro)
    def test_quality_options_and_missing_global_mid(self):
        macro=self.macro(create_quality_histograms=False)
        self.assertNotIn('HistogramDataSeriesConfig',macro)
        self.assertNotIn('createQualityHistogram(',macro)
        macro=self.macro(create_quality_scene=False,create_quality_histograms=False,create_bad_cells=False)
        self.assertNotIn('createQualityExtrema(sim, subchannelRegions',macro)
        self.assertNotIn('qualitySurfaces.add',macro)
        macro=self.macro(n_planes=0,key_planes=False)
        self.assertIn('"Quality_Section_Z_25mm"',macro)
        for value in (0,501,True,1.2):
            with self.assertRaises(ValueError):self.macro(quality_bins=value)
    def test_quality_and_gap_controls_in_dialog(self):
        dialog=StarCcmExportDialog(mesh_result=self.result,bundle_model=self.model)
        try:
            self.assertTrue(dialog.chk_histograms.isChecked())
            self.assertEqual(dialog.spin_quality_bins.value(),50)
            self.assertFalse(dialog.chk_gap_sections.isEnabled())
            dialog.rb_inter_fuse.setChecked(True)
            self.assertTrue(dialog.chk_gap_sections.isEnabled())
            dialog.chk_histograms.setChecked(False)
            self.assertFalse(dialog.spin_quality_bins.isEnabled())
        finally:dialog.deleteLater()
    def test_java_quality_helpers_assign_metric_parts_and_histogram_bins(self):
        import shutil, subprocess, tempfile
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
            self.skipTest('JDK compiler unavailable')
        macro=self.macro()
        methods=macro[macro.index('    private void createQualityScene'):macro.index('    private double measureArea')]
        harness='''import java.util.*;
class CheckQuality {
METHODS
<T> T findOwned(Simulation sim,Object manager,String name,Class<T> type) { return null; }
void own(Simulation sim,Object object) {}
static class NamedObject {}
static class Region extends NamedObject {}
static class FieldFunction { String getPresentationName() { return "Cell Quality"; } }
static class FvRepresentation {}
enum ScalarFillMode { NATIVE }
static class Input { List<?> parts; void setObjects(List<?> p) { parts=p; } }
static class Quantity { FieldFunction ff; void setFieldFunction(FieldFunction f) { ff=f; } }
static class ScalarDisplayer {
    Input input=new Input(); Quantity quantity=new Quantity(); ScalarFillMode fill; FvRepresentation rep;
    void setPresentationName(String n) {}
    void setRepresentation(FvRepresentation r) { rep=r; }
    Input getInputParts() { return input; }
    Quantity getScalarDisplayQuantity() { return quantity; }
    void setFillMode(ScalarFillMode f) { fill=f; }
}
static class DisplayerManager {
    ScalarDisplayer scalar=new ScalarDisplayer();
    ScalarDisplayer createScalarDisplayer(String s) { return scalar; }
}
static class Scene {
    DisplayerManager dm=new DisplayerManager(); String name;
    void setPresentationName(String n) { name=n; }
    DisplayerManager getDisplayerManager() { return dm; }
    void resetCamera() {}
}
static class SceneManager { Scene scene; Scene createScene() { scene=new Scene(); return scene; } }
static class RepresentationManager { Object getObject(String name) { return new FvRepresentation(); } }
enum VariableType { SCALAR }
enum SimDataSourceType { PARTS }
enum WeightingMode { FREQUENCY }
enum XyPlotTypeEnum { HISTOGRAM }
static class PlotAxisInput {
    static class ScalarFunctionInput { FieldFunction ff; ScalarFunctionInput(FieldFunction f) { ff=f; } }
    FieldFunction ff;
    PlotAxisInput(VariableType v) {}
    PlotAxisInput(VariableType v, ScalarFunctionInput f) { ff=f.ff; }
}
static class HistogramDataSeriesConfig {
    List<?> parts; PlotAxisInput axis; WeightingMode weighting;
    HistogramDataSeriesConfig(SimDataSourceType t,List<?> p,Object none,PlotAxisInput a,PlotAxisInput w,WeightingMode mode) { parts=p;axis=a;weighting=mode; }
}
static class BinningDescriptor { int bins; void setNumberOfBins(int b) { bins=b; } }
static class PartAxisType { BinningDescriptor bins=new BinningDescriptor(); BinningDescriptor hasBinningDescriptor() { return bins; } }
static class AxisTypeManager {
    PartAxisType axis=new PartAxisType();
    PartAxisType getAxisType(String name) { if (!name.equals("Bottom Axis Binned Data")) throw new AssertionError(); return axis; }
}
static class PartGroupDataSet { AxisTypeManager axes=new AxisTypeManager(); AxisTypeManager getAxisTypeManager() { return axes; } }
static class Cartesian2DPlot {
    String name, title; PartGroupDataSet data=new PartGroupDataSet(); HistogramDataSeriesConfig series;
    void setPresentationName(String n) { name=n; }
    void setTitle(String t) { title=t; }
    List<?> getDataSeriesOrder() { return List.of(data); }
}
static class PlotManager {
    Cartesian2DPlot plot;
    Cartesian2DPlot createCartesian2DPlot(String name,List<XyPlotTypeEnum> modes,HistogramDataSeriesConfig series) {
        if (!modes.equals(List.of(XyPlotTypeEnum.HISTOGRAM))) throw new AssertionError();
        plot=new Cartesian2DPlot(); plot.series=series; return plot;
    }
}
static class Simulation {
    SceneManager scenes=new SceneManager(); PlotManager plots=new PlotManager();
    SceneManager getSceneManager() { return scenes; }
    PlotManager getPlotManager() { return plots; }
    RepresentationManager getRepresentationManager() { return new RepresentationManager(); }
}
public static void main(String[] args) {
    CheckQuality check=new CheckQuality(); Simulation sim=new Simulation(); FieldFunction ff=new FieldFunction();
    List<NamedObject> surfaces=List.of(new NamedObject()); List<Region> regions=List.of(new Region());
    check.createQualityScene(sim,surfaces,ff,"quality");
    ScalarDisplayer scalar=sim.scenes.scene.dm.scalar;
    if (scalar.input.parts!=surfaces || scalar.quantity.ff!=ff || scalar.fill!=ScalarFillMode.NATIVE || scalar.rep==null) throw new AssertionError("empty scene");
    check.createQualityHistogram(sim,regions,ff,"hist","< 1e-5",37);
    Cartesian2DPlot plot=sim.plots.plot;
    if (!plot.title.contains("bad: < 1e-5")) throw new AssertionError("missing threshold label");
    if (!plot.series.parts.equals(regions) || plot.series.axis.ff!=ff || plot.series.weighting!=WeightingMode.FREQUENCY || plot.data.axes.axis.bins.bins!=37) throw new AssertionError("unconfigured histogram");
    try { check.createQualityScene(sim,List.of(),ff,"empty"); throw new AssertionError("accepted empty surface list"); }
    catch (IllegalStateException expected) {}
}}
'''.replace('METHODS',methods)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'CheckQuality.java';path.write_text(harness,encoding='utf-8')
            r=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
