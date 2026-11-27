"""Generic TDC: physical closure, shared UI/profile, numerical windows and native contracts."""
import os,json,tempfile,subprocess,shutil,unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
import test_compact_star_export as fixture
from starccm_tdc_plan import build_plan,result_from_means,validate_tdc
from starccm_tdc_export import render_controller,write_bundle
from starccm_export_profile import validate_options


def enable_tdc(d):
    d.rb_inter_fuse.setChecked(True);d.rb_wall_60.setChecked(True);d.rb_turb_srh.setChecked(True)
    d.heat_enabled.setChecked(True);d.tdc_enabled.setChecked(True)
    d._pairs=[dict(first='Inlet',second='Outlet',kind='fully_developed',mass_flow=.1,mass_flow_auto=True)]
    return d

class UnifiedTdcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def plan(self,d):return build_plan(d.mesh_result,d.bundle_model,d.read_options(),d.read_fluid(),d.yplus_data)
    def test_shared_settings_no_reference_lock_and_profile_roundtrip(self):
        d=enable_tdc(self.dialog());d.mean_checkboxes['temperature'].setChecked(True);d.mean_checkboxes['velocity_i'].setChecked(True)
        values=d.read_options();self.assertEqual(values['export_mode'],'tdc');validate_options(values,2)
        self.assertTrue(d.mean_group.isEnabled());self.assertEqual(d.tabs.count(),8)
        other=self.dialog();other.apply_options(values);self.assertEqual(other.read_options(),values)
        code=render_controller(self.plan(d),values)
        self.assertNotIn('WALLS1',code);self.assertNotIn('Reference geometry is fixed',code);self.assertNotIn('TMC_',code)
        self.assertIn('"Velocity_i"',code)
        self.assertIn('case "Cp":return "Cp"',code);self.assertNotIn('param("Cp",',code)
        self.assertIn('setSyncName(true)',code)
    def test_missing_periodic_and_stale_gap_rejected_without_mutating_gui(self):
        d=enable_tdc(self.dialog());values=d.read_options();before=deepcopy(values)
        bad=deepcopy(values);bad['workflow']['boundary_pairs']=[]
        with self.assertRaisesRegex(ValueError,'вход'):d.apply_options(bad)
        self.assertEqual(d.read_options(),before)
        bad=deepcopy(values);bad['workflow']['tdc_settings']['gaps']=['stale']
        with self.assertRaises(ValueError):build_plan(d.mesh_result,d.bundle_model,bad,d.read_fluid(),d.yplus_data)
    def test_energy_storage_signs_ratio_of_means_and_guard(self):
        # A receives 12W, stores2W; B receives -11W, releases1W: Q_A=Q_B=10W.
        r=result_from_means(12,-11,0,4,2,0,2,2,.5,2,5,.01,.05)
        self.assertTrue(r['valid']);self.assertAlmostEqual(r['tdc'],1.)
        inverse=result_from_means(-12,11,4,0,0,2,2,-2,.5,2,5,.01,.05)
        self.assertEqual(inverse['tdc'],r['tdc'])
        for changes in ((12,-11,0,4,2,0,2,.001),(12,0,0,4,2,0,2,2),(12,-11,0,4,2,0,2,-2)):
            self.assertFalse(result_from_means(*changes,.5,2,5,.01,.05)['valid'])
    def test_every_exchange_required_and_molecular_option_rejected(self):
        d=enable_tdc(self.dialog());v=d.read_options();v['workflow']['tdc_settings']['conduction']=True
        with self.assertRaisesRegex(ValueError,'поправка'):build_plan(d.mesh_result,d.bundle_model,v,d.read_fluid(),d.yplus_data)
        v=d.read_options();v['workflow']['boundary_pairs'][0].update(mass_flow_auto=False,mass_flow=999.)
        with self.assertRaisesRegex(ValueError,'Расход'):build_plan(d.mesh_result,d.bundle_model,v,d.read_fluid(),d.yplus_data)
    def test_bundle_atomic_dependencies_and_exact_controller_compilation(self):
        import test_tmc_hybrid as java_test
        command,java=java_test.compiler()
        if command is None:self.skipTest('JDK unavailable; not a Siemens SDK test')
        d=enable_tdc(self.dialog());d.mean_checkboxes['temperature'].setChecked(True)
        with tempfile.TemporaryDirectory() as tmp,patch('mesh_subchannel.export_subchannel_plot3d',side_effect=lambda r,p,**k:Path(p).write_text('XYZ')):
            root=Path(tmp);paths=write_bundle(root,'mesh.xyz',d.mesh_result,d.bundle_model,d.read_fluid(),d.yplus_data,d.read_options(),lambda *x:None)
            self.assertEqual(len(paths),5);source=paths[1].read_text();control=paths[2].read_text()
            self.assertIn('Subchannel_1_Section_Z_30mm',source);self.assertIn('threshold(sim,reportInlets,mask1,"TDC_Sub1_Inlet")',source)
            self.assertNotIn('createTimeMean(sim,subchannelRegions,"Temperature"',source)
            self.assertIn('setDefinition(rr("qvSource"))',control);self.assertIn('cumulative.add(now,values)',control)
            self.assertIn('if(valid)r.put("TDC_Effective"',control);self.assertIn('Unavailable_TDC_',control)
            java_test.write_stubs(root);(root/'macro').mkdir();shutil.copy(paths[2],root/'macro'/paths[2].name)
            r=subprocess.run(command+[str(root/'classes')]+[str(p) for p in root.rglob('*.java') if p not in paths],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            original={p:p.read_bytes() for p in paths}
            def cancel(n,text):
                if n==95:raise RuntimeError('cancel')
            with self.assertRaises(RuntimeError):write_bundle(root,'mesh.xyz',d.mesh_result,d.bundle_model,d.read_fluid(),d.yplus_data,d.read_options(),cancel)
            self.assertEqual(original,{p:p.read_bytes() for p in paths})

    def test_equivalent_periodic_gaps_are_counted_not_assumed_three(self):
        d=enable_tdc(self.dialog());cat=d._surface_catalog
        left=[r for r in cat['sides'] if r['source']==1 and not r['shared']]
        right=[r for r in cat['sides'] if r['source']==2 and not r['shared']]
        self.assertEqual(len(left),2)
        for a,b in zip(left,right):d._pairs.append(dict(first=a['id'],second=b['id'],kind='periodic'))
        p=self.plan(d)
        self.assertEqual(len(p['exchanges']),1)
        self.assertAlmostEqual(p['area'],left[0]['area'])
        self.assertEqual(sum(x['method']=='boundary' for x in p['paths']),4)
        d._show_tdc_exchange();self.assertIn('обмен TDC',d.preview_selection.text())

    def test_java_derived_kernel_and_csv_resume_use_actual_generated_code(self):
        import test_tmc_hybrid as jt
        from starccm_tdc_export import replace_method
        cmd,java=jt.compiler()
        if cmd is None:self.skipTest('JDK unavailable')
        d=enable_tdc(self.dialog());d.tdc_components.setChecked(False);code=render_controller(self.plan(d),d.read_options())
        def method(name):
            marker='UNIQUE_MARKER';changed=replace_method(code,name,marker)
            start=changed.index(marker);suffix=changed[start+len(marker):]
            return code[start:len(code)-len(suffix)]
        kernel=code[code.index('    static final class WeightedWindow'):code.rfind('}')]
        helpers='\n'.join(method(n) for n in ('derived','derivedKeys','loadTotal','writeCumulative'))
        area=self.plan(d)['area']
        harness='''import java.util.*;import java.nio.file.*;import java.nio.charset.*;import java.io.*;
class Check {
 static final String P="TDC_";Map<String,Object> sampled=new LinkedHashMap<>();Path dir;
 double value(String n){return n.equals("Cp")?2:n.equals("MinDeltaT")?.01:.05;}
 Path seriesDirectory(){return dir;}
 HELPERS
 KERNEL
 public static void main(String[] a)throws Exception {
  Check c=new Check();c.dir=Paths.get(a[0]);
  List<String> names=Arrays.asList("TDC_A_Exchange_NoStorage","TDC_B_Exchange_NoStorage","TDC_A_SensibleEnergy","TDC_B_SensibleEnergy","TDC_DeltaT_BulkLength","TDC_MassFluxRef","TDC_A_OtherOut","TDC_B_OtherOut");
  for(String n:names)c.sampled.put(n,new Object());
  WeightedWindow w=new WeightedWindow(names);w.add(0,new double[]{12,-11,0,2,2,5,0,0});w.add(2,new double[]{12,-11,4,0,2,5,0,0});
  Map<String,Double> r=c.derived(w);if(r.get("ResultValid")!=1 || Math.abs(r.get("Exchange_A_W")-10)>1e-12 || Math.abs(r.get("Exchange_B_W")-10)>1e-12)throw new AssertionError(r.toString());
  if(Math.abs(r.get("TDC_Effective")-10/(AREA*2*5*2))>1e-8)throw new AssertionError("ratio");
  WeightedWindow fluct=new WeightedWindow(names);fluct.add(0,new double[]{1,-1,0,0,1,5,0,0});fluct.add(2,new double[]{9,-9,0,0,3,5,0,0});
  if(Math.abs(c.derived(fluct).get("TDC_Effective")-5/(AREA*2*5*2))>1e-8)throw new AssertionError("mean of instantaneous ratios used");
  WeightedWindow lateral=new WeightedWindow(names);lateral.add(0,new double[]{12,-11,0,2,2,5,2,-2});lateral.add(2,new double[]{12,-11,4,0,2,5,6,-6});
  Map<String,Double> lr=c.derived(lateral);if(lr.get("ResultValid")!=1 || Math.abs(lr.get("Exchange_A_W")-6)>1e-12 || Math.abs(lr.get("Exchange_B_W")-6)>1e-12 || Math.abs(lr.get("OtherOut_A_W")-4)>1e-12)throw new AssertionError("lateral subtraction "+lr);
  c.writeCumulative(w);if(Files.readAllLines(c.dir.resolve("cumulative.csv")).size()!=2)throw new AssertionError("CSV newline");
  String header="time_s,"+String.join(",",names)+"\\n";
  Files.writeString(c.dir.resolve("block_00001.csv"),header+"0,12,-11,0,2,2,5,0,0\\n1,12,-11,2,1,2,5,0,0\\n");
  Files.writeString(c.dir.resolve("block_00002.csv"),header+"1,12,-11,2,1,2,5,0,0\\n2,12,-11,4,0,2,5,0,0\\n");
  WeightedWindow total=c.loadTotal(c.dir,2);if(total.count!=3 || total.duration()!=2 || c.derived(total).get("ResultValid")!=1)throw new AssertionError("duplicate boundary or wrong total");
  WeightedWindow bad=new WeightedWindow(names);bad.add(0,new double[]{12,-11,0,2,0,5,0,0});bad.add(2,new double[]{12,-11,4,0,0,5,0,0});
  if(c.derived(bad).containsKey("TDC_Effective") || c.derived(bad).get("ResultValid")!=0)throw new AssertionError("accepted zero delta");
  System.out.println("checks passed");
 }
}'''.replace('HELPERS',helpers).replace('KERNEL',kernel).replace('AREA',repr(area))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'Check.java';p.write_text(harness)
            r=subprocess.run([java,str(p),tmp],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn('checks passed',r.stdout)

    def test_merged_physical_rod_heat_is_partitioned_by_source_masks(self):
        d=enable_tdc(self.dialog());d.rb_wall_by_rod.setChecked(True)
        values=d.read_options();p=self.plan(d);code=render_controller(p,values)
        shared=next(row for row in p['catalog']['rods'] if len(row['sources'])==2)
        self.assertIn(f'"TDC_Sub1_Heat_{shared["id"]}"',code)
        self.assertIn(f'"TDC_Sub2_Heat_{shared["id"]}"',code)
        self.assertIn('"A_Exchange_NoStorage"',code);self.assertIn('"B_Exchange_NoStorage"',code)
        self.assertNotIn('"Sub1_Exchange_NoStorage"',code)

    def test_separate_regions_generate_interface_side_dependencies(self):
        d=enable_tdc(self.dialog());d.rb_inter_intf.setChecked(True)
        d._pairs=[dict(first=f'Inlet_s{n}',second=f'Outlet_s{n}',kind='fully_developed',mass_flow=.1,mass_flow_auto=True) for n in (1,2)]
        p=self.plan(d);self.assertFalse(p['catalog']['fused'])
        from starccm_macro_generator import generate_starccm_java_macro
        code=generate_starccm_java_macro('mesh.xyz',d.mesh_result,d.bundle_model,d.read_fluid(),d.yplus_data,d.read_options())
        self.assertIn('threshold(sim,Collections.singletonList(reportInlets.get(0)),tdcMask1,"TDC_Sub1_Inlet")',code)
        self.assertIn('"Subchannel_1_Domain"',code)

    def test_other_length_and_pitch_do_not_use_reference_geometry(self):
        from bundle_geometry import BundleModel
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        from starccm_export_dialog import StarCcmExportDialog
        model=BundleModel(pitch=12.2);model.selected_subchannels={18,22}
        mesh=build_mesh_from_bundle_model(model,MeshParams(ni=15,nj=12,nz=2,z_len=.12))
        d=enable_tdc(StarCcmExportDialog(mesh_result=mesh,bundle_model=model));self.addCleanup(d.deleteLater)
        plan=self.plan(d);self.assertEqual(plan['height'],.12)
        code=render_controller(plan,d.read_options());self.assertIn('param("Length",0.12,',code)
        d.tdc_blocks.setChecked(False);code=render_controller(self.plan(d),d.read_options())
        self.assertIn('param("PlannedBlocks",1,',code)

    def test_third_neighbor_is_not_misattributed_to_selected_pair(self):
        from bundle_geometry import BundleModel
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        from starccm_export_dialog import StarCcmExportDialog
        model=BundleModel(pitch=11.64);model.selected_subchannels={18,22,23}
        mesh=build_mesh_from_bundle_model(model,MeshParams(ni=15,nj=12,nz=2,z_len=.1))
        d=enable_tdc(StarCcmExportDialog(mesh_result=mesh,bundle_model=model));self.addCleanup(d.deleteLater)
        with self.assertRaisesRegex(ValueError,'неизвестный'):d.read_options()
