"""Distinct side exchanges, not equal-gap assumptions, determine the target residual."""
import os,tempfile,subprocess,shutil
from copy import deepcopy
from pathlib import Path
import unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
import test_compact_star_export as fixture
from test_unified_tdc import enable_tdc
from starccm_tdc_plan import build_plan,result_from_means
from starccm_tdc_paths import side_paths,account_paths,channel_labels
from starccm_tdc_export import render_controller,replace_method
from starccm_tdc_flux import BOUNDARY_SUPPORT


def lateral(d):
    rows=d._surface_catalog['sides']
    a=[r for r in rows if r['source']==1 and not r['shared']]
    b=[r for r in rows if r['source']==2 and not r['shared']]
    # One periodic connection, the remaining two faces symmetry, as requested.
    d._pairs.append(dict(first=a[0]['id'],second=b[0]['id'],kind='periodic'))
    d._conditions=[dict(surface=r['id'],kind='symmetry',value=0.) for r in (a[1],b[1])]
    d._tdc_refresh();return a,b


class PathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def plan(self,d):return build_plan(d.mesh_result,d.bundle_model,d.read_options(),d.read_fluid(),d.yplus_data)
    def test_periodic_and_symmetry_are_independent_paths(self):
        d=enable_tdc(self.dialog());a,b=lateral(d);p=self.plan(d)
        self.assertEqual(p['target']['connection'],'Gap_Sub1_Sub2')
        self.assertEqual([x['method'] for x in p['paths']].count('target'),2)
        self.assertEqual([x['method'] for x in p['paths']].count('boundary'),2)
        self.assertEqual([x['method'] for x in p['paths']].count('zero'),2)
        code=render_controller(p,d.read_options())
        self.assertIn('field("BoundaryConductionHeatFlux")',code)
        self.assertIn('sidePart(modelRegions.get(0),"'+a[0]['id']+'","SelectedInterface_2")',code)
        self.assertIn('w.mean("A_OtherOut")',code)
        self.assertNotIn('field("BoundaryHeatFlux")',code)
        self.assertIn('SidePairRelative',code);self.assertIn('Zero-flux BC changed',code)
    def test_subtraction_signs_and_energy_reference(self):
        # Total A residual10W, other interface carries+4W; target6W, B agrees.
        r=result_from_means(12,-11,0,4,2,0,2,2,.5,2,5,.01,.05,other_a=4,other_b=-4)
        self.assertTrue(r['valid']);self.assertAlmostEqual(r['q_a'],6);self.assertAlmostEqual(r['tdc'],.6)
        # Heat entering A through the other side is negative, so increases target outflow.
        r=result_from_means(12,-11,0,4,2,0,2,2,.5,2,5,.01,.05,other_a=-4,other_b=4)
        self.assertTrue(r['valid']);self.assertAlmostEqual(r['q_a'],14)
        d=enable_tdc(self.dialog());lateral(d);code=render_controller(self.plan(d),d.read_options())
        self.assertIn('energy.getFunctionName()',code);self.assertNotIn('BoundaryAdvectionHeatFlux',code)
    def test_open_path_cannot_be_declared_zero(self):
        d=enable_tdc(self.dialog());a,b=lateral(d);v=d.read_options();v['workflow']['tdc_settings']['path_methods'][a[0]['id']]='zero'
        with self.assertRaisesRegex(ValueError,'нулевым'):build_plan(d.mesh_result,d.bundle_model,v,d.read_fluid(),d.yplus_data)
    def test_target_switch_and_profile_preserve_measuring_methods(self):
        d=enable_tdc(self.dialog());lateral(d)
        d.tdc_target.setCurrentIndex(1)
        # The internal Fuse cut is now another unknown: no silent zero/equivalence.
        with self.assertRaisesRegex(ValueError,'неизвестный'):d.read_options()
        for i,p in enumerate(d._tdc_rows):
            if p['kind']=='fuse':
                c=d.tdc_paths_table.cellWidget(i,3);c.setCurrentIndex(c.findData('reconstruct'))
        with self.assertRaisesRegex(ValueError,'скалярное'):d.read_options()
        d.tdc_reconstruction.setChecked(True);v=d.read_options()
        other=self.dialog();other.apply_options(v);self.assertEqual(other.read_options(),v)
        code=render_controller(self.plan(d),v)
        self.assertIn('field("EffectiveConductivity")',code);self.assertIn('grad(${Temperature})',code)
        self.assertNotIn('BoundaryConductionHeatFlux',code)
        d.tdc_target.setCurrentIndex(0);self.assertNotIn('target',d._tdc_read()['path_methods'].values())
    def test_user_report_is_explicit_signed_watts_and_never_overwritten(self):
        d=enable_tdc(self.dialog());a,b=lateral(d)
        for i,p in enumerate(d._tdc_rows):
            if p['kind']=='periodic':
                c=d.tdc_paths_table.cellWidget(i,3);c.setCurrentIndex(c.findData('report'));d.tdc_paths_table.cellWidget(i,4).setText('SidePower_'+str(p['source']))
        v=d.read_options();code=render_controller(self.plan(d),v)
        self.assertIn('externalPower("Path_'+a[0]['id']+'_Out","SidePower_1")',code)
        self.assertIn('input.getUnits().equals(sim.getUnitsManager().getObject("W"))',code)
        self.assertNotIn('createReport(type)',code[code.index('private void externalPower'):])
        v['workflow']['tdc_settings']['path_reports'][a[0]['id']]='bad name'
        with self.assertRaises(ValueError):build_plan(d.mesh_result,d.bundle_model,v,d.read_fluid(),d.yplus_data)
    def test_measured_third_neighbor_can_be_accounted_for(self):
        from bundle_geometry import BundleModel
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        from starccm_export_dialog import StarCcmExportDialog
        m=BundleModel(pitch=11.64);m.selected_subchannels={18,22,23};r=build_mesh_from_bundle_model(m,MeshParams(ni=15,nj=12,nz=2,z_len=.1))
        d=enable_tdc(StarCcmExportDialog(mesh_result=r,bundle_model=m));self.addCleanup(d.deleteLater)
        d._tdc_refresh()
        with self.assertRaisesRegex(ValueError,'неизвестный'):d.read_options()
        for i,p in enumerate(d._tdc_rows):
            if p['neighbor']==3:
                c=d.tdc_paths_table.cellWidget(i,3);c.setCurrentIndex(c.findData('report'));d.tdc_paths_table.cellWidget(i,4).setText('PowerToThird')
        v=d.read_options();p=self.plan(d)
        self.assertTrue(any(x['neighbor']==3 and x['method']=='report' for x in p['paths']))
        self.assertTrue(any('сосед · Подканал 3' in d.tdc_connections.item(i,1).text() for i in range(d.tdc_connections.rowCount())))
    def test_native_side_selector_executes_and_rejects_parent_and_ambiguity(self):
        import test_tmc_hybrid as jt
        cmd,java=jt.compiler()
        if cmd is None:self.skipTest('JDK unavailable; not Siemens SDK')
        helper=BOUNDARY_SUPPORT[:BOUNDARY_SUPPORT.index('    private void externalPower')]
        code='''import java.util.*;
class Check {
 static class NamedObject {String name;NamedObject(String n){name=n;}String getPresentationName(){return name;}}
 static class Boundary extends NamedObject {Boundary(String n){super(n);}}
 static class InterfaceBoundary extends Boundary {InterfaceBoundary(String n){super(n);}}
 static class Region {List<Object> list=new ArrayList<>();Object getBoundaryManager(){return list;}}
 Collection<?> objects(Object o){return (Collection<?>)o;}
 HELPERS
 public static void main(String[] x){Check c=new Check();Region r=new Region();Boundary parent=new Boundary("Side_s1_R1_R2");InterfaceBoundary child=new InterfaceBoundary("Side_s1_R1_R2 [SelectedInterface_2 1]");
 r.list.add(parent);r.list.add(child);r.list.add(new InterfaceBoundary("Side_s1_R1_R2 [SelectedInterface_20 1]"));
 if(c.sidePart(r,"Side_s1_R1_R2","SelectedInterface_2")!=child)throw new AssertionError("wrong side");
 try{c.sidePart(r,"Side_s1_R1_R2","SelectedInterface_3");throw new AssertionError("parent fallback");}catch(IllegalStateException ok){}
 r.list.add(new InterfaceBoundary("Side_s1_R1_R2 [SelectedInterface_2 2]"));try{c.sidePart(r,"Side_s1_R1_R2","SelectedInterface_2");throw new AssertionError("ambiguity");}catch(IllegalStateException ok){}
 }}'''.replace('HELPERS',helper)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'Check.java';p.write_text(code);run=subprocess.run([java,str(p)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    def test_generated_native_and_reconstructed_controllers_compile(self):
        import test_tmc_hybrid as jt
        cmd,java=jt.compiler()
        if cmd is None:self.skipTest('JDK unavailable; not Siemens SDK')
        d=enable_tdc(self.dialog());lateral(d)
        variants=[(self.plan(d),d.read_options())]
        d.tdc_target.setCurrentIndex(1)
        for i,p in enumerate(d._tdc_rows):
            if p['kind']=='fuse':
                c=d.tdc_paths_table.cellWidget(i,3);c.setCurrentIndex(c.findData('reconstruct'))
        d.tdc_reconstruction.setChecked(True);variants.append((self.plan(d),d.read_options()))
        for plan,options in variants:
            with tempfile.TemporaryDirectory() as t:
                root=Path(t);jt.write_stubs(root);(root/'macro').mkdir()
                (root/'macro'/'TDC_Hybrid.java').write_text(render_controller(plan,options))
                run=subprocess.run(cmd+[str(root/'classes')]+[str(p) for p in root.rglob('*.java')],capture_output=True,text=True,timeout=60)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_unequal_guide_diameter_does_not_require_equivalent_gaps(self):
        from bundle_geometry import BundleModel
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        from starccm_export_dialog import StarCcmExportDialog
        m=BundleModel(pitch=11.64);m.selected_subchannels={18,22}
        m.rods[13].rod_type='guide';m.rods[13].diameter=11.
        for sub in m.subchannels.values():m.calc_hydraulics(sub)
        r=build_mesh_from_bundle_model(m,MeshParams(ni=21,nj=14,nz=2,z_len=.1))
        d=enable_tdc(StarCcmExportDialog(mesh_result=r,bundle_model=m));self.addCleanup(d.deleteLater)
        # Pair the two widest external sides; narrow internal gap has another area.
        sides=d._surface_catalog['sides'];a=max((p for p in sides if p['source']==1 and not p['shared']),key=lambda p:p['area'])
        b=max((p for p in sides if p['source']==2 and not p['shared']),key=lambda p:p['area'])
        d._pairs.append(dict(first=a['id'],second=b['id'],kind='periodic'))
        d._conditions=[dict(surface=p['id'],kind='symmetry',value=0.) for p in sides if not p['shared'] and p['id'] not in (a['id'],b['id'])]
        d._tdc_refresh();plan=self.plan(d)
        self.assertNotAlmostEqual(plan['area'],a['area'],places=7)
        self.assertIn('НК Ø11',d.tdc_composition.text());self.assertEqual(plan['target']['kind'],'fuse')
