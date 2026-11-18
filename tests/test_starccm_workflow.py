import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from types import SimpleNamespace
import json, sys, tempfile, unittest, shutil, subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from starccm_export_dialog import StarCcmExportDialog
from starccm_export_profile import DEFAULTS, save_profile, load_profile, validate_options
from starccm_macro_support import JAVA_SUPPORT

class ExportProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def dialog(self):
        dialog=StarCcmExportDialog(mesh_result=SimpleNamespace(params=SimpleNamespace(z_len=.05,h1=5e-6),subchannels_count=2))
        self.addCleanup(dialog.deleteLater)
        return dialog
    def test_roundtrip_all_dialog_controls(self):
        a=self.dialog();a.rb_inter_fuse.setChecked(True);a.rb_wall_rod.setChecked(True)
        a.rb_turb_srh.setChecked(True);a.rb_eos_iapws.setChecked(True)
        a.spin_quality_bins.setValue(77);a.spin_n_planes.setValue(17);a.spin_sub_n_planes.setValue(5)
        a.chk_bad_cells.setChecked(False);a.chk_summary.setChecked(False)
        a.sub_checkboxes[0].setChecked(False)
        values=a.read_options()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.json';save_profile(values,path)
            b=self.dialog();b.apply_options(load_profile(path,2))
            self.assertEqual(b.read_options(),values)
    def test_invalid_profile_does_not_mutate_dialog(self):
        dialog=self.dialog();before=dialog.read_options()
        for patch in (dict(quality_bins=True),dict(selected_subchannels=[3]),dict(rod_wall_mode='unknown'),dict(inter_fuse=True)):
            with self.subTest(patch=patch), self.assertRaises(ValueError):dialog.apply_options(dict(before,**patch))
            self.assertEqual(dialog.read_options(),before)
    def test_version_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.json'
            for text in ('{"format":"meshBuilder-star-export","version":2,"options":{}}',
                         '{"version":1,"version":1}'):
                path.write_text(text)
                with self.assertRaises(ValueError):load_profile(path)
            save_profile(dict(DEFAULTS,selected_subchannels=[1]),path)
            self.assertEqual(load_profile(path,1)['selected_subchannels'],[1])
    def test_defaults_do_not_allow_hidden_topology_changes(self):
        for patch in (dict(inner_fuse=False),dict(create_physics=False),dict(n_planes=-1),dict(selected_subchannels=[True])):
            with self.assertRaises(ValueError):validate_options(dict(DEFAULTS,**patch))

class ManagedJavaTests(unittest.TestCase):
    def test_actual_ownership_and_region_guards_execute_twice(self):
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:
            self.skipTest('JDK compiler unavailable')
        base=JAVA_SUPPORT[:JAVA_SUPPORT.index('    private ThresholdPart threshold')]
        guards=JAVA_SUPPORT[JAVA_SUPPORT.index('    private List<Region> preparedRegions'):JAVA_SUPPORT.index('    private void markBoundaryRoles')]
        grouping=JAVA_SUPPORT[JAVA_SUPPORT.index('    private void groupManaged'):JAVA_SUPPORT.index('    private String csv')]
        harness='''import java.util.*;
class CheckManaged {
HELPERS
public static class NamedObject {
    String name; TagGroup tagGroup=new TagGroup();
    public String getPresentationName() { return name; }
    public void setPresentationName(String n) { name=n; }
    public TagGroup getTagGroup() { return tagGroup; }
}
public static class TagGroup { List<Tag> tags=new ArrayList<>(); public List<Tag> getObjects() { return tags; } }
public static class Tag extends NamedObject {}
public static class TagManager {
    List<Tag> tags=new ArrayList<>();
    public List<Tag> getObjects() { return tags; }
    public Tag createNewUserTag(String n) { Tag t=new Tag();t.name=n;tags.add(t);return t; }
    public void setTags(NamedObject o,List<Tag> t) { o.tagGroup.tags=new ArrayList<>(t); }
}
public static class Report extends NamedObject {}
public static class NativeGroups {
    Map<String,List<?>> grouped=new HashMap<>();
    public void groupObjects(String name,Collection<?> values,boolean flag) { grouped.put(name,new ArrayList<>(values)); }
}
public static class NeoObjectVector { public NeoObjectVector(Object[] o) {} }
public static class ReportManager {
    List<Report> reports=new ArrayList<>(); NativeGroups groups=new NativeGroups();
    public List<Report> getObjects() { return reports; }
    public NativeGroups getGroupsManager() { return groups; }
    public <T extends Report> T createReport(Class<T> type) {
        try { T r=type.getDeclaredConstructor().newInstance();reports.add(r);return r; }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
}
public static class Region extends NamedObject {}
public static class RegionManager {
    List<Region> regions=new ArrayList<>(); public List<Region> getRegions() { return regions; }
}
public static class Simulation {
    TagManager tm=new TagManager(); ReportManager rm=new ReportManager(); RegionManager regions=new RegionManager();
    public <T> T get(Class<T> type) { return type.cast(tm); }
    public ReportManager getReportManager() { return rm; }
    public RegionManager getRegionManager() { return regions; }
    public void println(String m) {}
}
public static void main(String[] args) {
    CheckManaged c=new CheckManaged(); Simulation sim=new Simulation();
    Report manual=new Report();manual.name="Manual";sim.rm.reports.add(manual);
    try { c.ownedReport(sim,"Manual",Report.class);throw new AssertionError("overwrote user report"); }
    catch (IllegalStateException expected) {}
    Report a=c.ownedReport(sim,"Quality_Min_Test",Report.class);
    c.mark(sim,a,"UserCustomTag");
    Report b=c.ownedReport(sim,"Quality_Min_Test",Report.class);
    if (a!=b || sim.rm.reports.size()!=2 || !c.tagged(a,"UserCustomTag")) throw new AssertionError("duplicate or lost user tags");
    c.groupManaged(sim,sim.rm,"Reports");c.groupManaged(sim,sim.rm,"Reports");
    if (sim.rm.groups.grouped.get("meshBuilder_Quality").size()!=1 || c.tagged(manual,OWNER)) throw new AssertionError("group changed user object");
    Report legacy=new Report();legacy.name="MB_Legacy";sim.rm.reports.add(legacy);c.mark(sim,legacy,OWNER);
    if (c.findOwned(sim,sim.rm,"MB_Legacy",Report.class)!=legacy || !legacy.name.equals("Legacy")) throw new AssertionError("legacy display migration");
    if (c.findOwned(sim,sim.rm,"MB_Legacy",Report.class)!=legacy) throw new AssertionError("clean display not reused");
    Report conflict=new Report();conflict.name="MB_Collision";sim.rm.reports.add(conflict);c.mark(sim,conflict,OWNER);
    Report user=new Report();user.name="Collision";sim.rm.reports.add(user);
    try { c.findOwned(sim,sim.rm,"MB_Collision",Report.class);throw new AssertionError("accepted display collision"); }
    catch (IllegalStateException expected) {}
    if (!conflict.name.equals("MB_Collision") || !user.name.equals("Collision")) throw new AssertionError("collision mutated objects");
    Region r1=new Region(),r2=new Region();r1.name="User renamed 1";r2.name="User renamed 2";
    sim.regions.regions.add(r2);sim.regions.regions.add(r1);
    c.mark(sim,r1,"meshBuilder.Mesh.abc");c.mark(sim,r2,"meshBuilder.Mesh.abc");
    c.mark(sim,r1,"meshBuilder.Source.1");c.mark(sim,r2,"meshBuilder.Source.2");
    if (c.preparedRegions(sim,"abc",2).get(0)!=r1) throw new AssertionError("lost source order");
    try { c.preparedRegions(sim,"different",2);throw new AssertionError("accepted different mesh"); }
    catch (IllegalStateException expected) {}
    try { c.preparedRegions(sim,"abc",1);throw new AssertionError("accepted changed region count"); }
    catch (IllegalStateException expected) {}
}
}
'''.replace('HELPERS',base+guards+grouping)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'CheckManaged.java';path.write_text(harness,encoding='utf-8')
            r=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

class WorkflowGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        from bundle_geometry import BundleModel
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        cls.model=BundleModel()
        ids=[i for i,s in cls.model.subchannels.items() if s.sub_type=='interior']
        cls.model.selected_subchannels={ids[0],next(i for i in ids[1:] if len(set(cls.model.subchannels[i].rod_ids)&set(cls.model.subchannels[ids[0]].rod_ids))==2)}
        cls.result=build_mesh_from_bundle_model(cls.model,MeshParams(ni=8,nj=10,nz=1))
    def macro(self,**options):
        from starccm_macro_generator import generate_starccm_java_macro
        return generate_starccm_java_macro('mesh.xyz',self.result,self.model,{}, {},options)
    def test_bad_cell_masks_counts_union_and_volume_check(self):
        macro=self.macro()
        for key,condition in [('CellQuality','< 1e-5'),('FaceValidity','< 1'),('VolumeChange','<= 0.01'),('SkewnessAngle','> 85')]:
            self.assertIn(f'"{key}", "{condition}", reportCounts',macro)
        for name in ('MB_BadAnyQuality','Quality_BadCells_Any','Quality_BadCount_Any','Quality_BadPercent_Any','NonPositiveVolume'):
            self.assertIn(name,macro)
        self.assertIn('ElementCountReport.class',macro)
        self.assertIn('"MB_Bad_" + key',macro)
        self.assertIn('masks.size()!=4',macro)
        self.assertNotIn('badUnion(sim,subchannelRegions',self.macro(create_bad_cells=False))
    def test_fingerprint_allows_analysis_updates_not_topology_changes(self):
        import re
        def signature(m):return re.search('exportFingerprint = "([a-f0-9]+)"',m).group(1)
        base=self.macro()
        self.assertEqual(signature(base),signature(self.macro(quality_bins=73,group_objects=False,n_planes=3)))
        self.assertNotEqual(signature(base),signature(self.macro(inter_fuse=True)))
        self.assertIn('if (!reuse)',base)
        self.assertIn('Same export detected: update managed analysis only',base)
        self.assertIn('Managed mesh cell count changed',base)
        self.assertIn('meshBuilder.Role.Inlet',base)
    def test_owned_objects_and_summary_do_not_silently_delete_user_data(self):
        macro=self.macro()
        self.assertIn('Name belongs to a user object',macro)
        self.assertIn('findOwned(sim,sim.getSceneManager()',macro)
        self.assertIn('findOwned(sim,sim.getPlotManager()',macro)
        self.assertIn('monitor.getReport()==report',macro)
        self.assertIn('groupManaged(sim,sim.getPartManager()',macro)
        self.assertIn('Files.createTempFile',macro)
        self.assertIn('report.getReportMonitorValue()',macro)
        self.assertIn('exportSettings',macro)
        self.assertNotIn('removeObjects(',macro)
        off=self.macro(group_objects=False,create_summary=False)
        self.assertNotIn('groupManaged(sim,sim.getPartManager()',off)
        self.assertNotIn('writeSummary(sim,subchannelRegions',off)
    def test_required_and_optional_field_functions(self):
        macro=self.macro(inter_fuse=True)
        self.assertIn('MB_SubchannelMask_1',macro)
        for name in ('MB_One','MB_X','MB_Y','MB_Z','MB_ZFraction','MB_Speed','MB_MassFluxMagnitude','MB_MassBalanceSigned','MB_EnergyBalanceSigned'):
            self.assertIn(name,macro)
        self.assertIn('supportFunctions(sim,',macro)
        self.assertIn('"MB_CellQuality"',macro)
        off=self.macro(create_field_functions=False)
        self.assertNotIn('supportFunctions(sim,',off)
        self.assertNotIn('getOrCreateFF(sim,"MB_MassBalanceSigned"',off)
