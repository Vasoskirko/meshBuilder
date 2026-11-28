"""Deleted rods become explicit fluid regions, never silently omitted CFD domains."""
import math,os,random,unittest
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from shapely.geometry import Polygon
from bundle_geometry import BundleModel
from meshbuilder.geometry.circle_polygon import circle_area,wetted_arc
from meshbuilder.geometry.hit_test import hit_subchannels

class RecoveryTests(unittest.TestCase):
    def complete(self,m):
        r=m.get_geometry_diagnostics();self.assertEqual(r.status,'ok',r.text())
        summary=m.get_total_assembly_summary()
        area=math.sqrt(3)/2*m.s_flat**2-sum(math.pi*x.diameter**2/4 for x in m.rods.values())
        wet=2*math.sqrt(3)*m.s_flat+sum(math.pi*x.diameter for x in m.rods.values())
        self.assertAlmostEqual(summary['total_a_fluid_mm2'],area,delta=1e-7)
        self.assertAlmostEqual(summary['total_p_wet_mm'],wet,delta=1e-7)
        for sid,sub in m.subchannels.items():
            self.assertTrue(set(sub.neighbor_sub_ids)<=m.subchannels.keys());self.assertNotIn(sid,sub.neighbor_sub_ids)
            for other in sub.neighbor_sub_ids:self.assertIn(sid,m.subchannels[other].neighbor_sub_ids)
    def test_every_single_rod_deletion_covers_fluid_and_preserves_hydraulics(self):
        for coord in BundleModel().coord_to_rod_id:
            with self.subTest(coord=coord):
                m=BundleModel();m.active_rod_coord=coord;m.delete_active_rod_manually();self.complete(m)
                self.assertTrue(any(s.sub_type=='recovered' for s in m.subchannels.values()))
    def test_seeded_multi_delete_clusters(self):
        coords=list(BundleModel().coord_to_rod_id)
        for seed in range(15):
            with self.subTest(seed=seed):
                m=BundleModel();rng=random.Random(seed);m.user_deleted_coords=set(rng.sample(coords,rng.randrange(2,19)));m.update_geometry();self.complete(m)
    def test_no_rods_and_collinear_rods_have_valid_geometry(self):
        for keep in (set(),{(-1,0),(0,0),(1,0)}):
            m=BundleModel();m.user_deleted_coords=set(m.coord_to_rod_id)-keep;m.update_geometry();self.complete(m)
    def test_restored_rods_remove_recovered_regions_without_stale_selection(self):
        m=BundleModel();m.active_rod_coord=(0,0);m.delete_active_rod_manually()
        sid=hit_subchannels(m,0,0)[0];m.select_subchannel(sid);before=m.export_dict()
        m.update_geometry();self.assertEqual(m.export_dict(),before)
        m.restore_deleted_rods();self.complete(m);self.assertFalse(m.recovery_notes)
        self.assertFalse(any(s.sub_type=='recovered' for s in m.subchannels.values()));self.assertFalse(m.selected_subchannels)
    def test_surviving_island_is_hole_not_double_selected_fluid(self):
        m=BundleModel();keep={(0,0),(1,0),(0,1),(-1,1),(-1,0),(0,-1),(1,-1)}
        m.user_deleted_coords=set(m.coord_to_rod_id)-keep;m.update_geometry();self.complete(m)
        recovered=next(s for s in m.subchannels.values() if s.sub_type=='recovered')
        self.assertTrue(recovered.polygon_holes);self.assertEqual(hit_subchannels(m,0,25),(recovered.sub_id,))
        regular=next(s for s in m.subchannels.values() if s.sub_type=='interior')
        self.assertEqual(hit_subchannels(m,*regular.fluid_center),(regular.sub_id,))
    def test_project_roundtrip_and_unaffected_ids(self):
        from bundle_project import geometry,restore_geometry
        m=BundleModel();m.active_rod_coord=(0,0);m.delete_active_rod_manually();m.select_all_subchannels()
        saved=geometry(m);restored=restore_geometry(saved);self.assertEqual(geometry(restored),saved);self.complete(restored)
    def test_mixed_cfd_selection_is_blocked_but_regular_subset_builds(self):
        from mesh_subchannel import build_mesh_from_bundle_model
        from mesh_core import MeshParams
        m=BundleModel();m.active_rod_coord=(0,0);m.delete_active_rod_manually();m.select_all_subchannels()
        p=MeshParams(ni=12,nj=12,nz=1,law='uniform',mode='shape_count')
        with self.assertRaisesRegex(ValueError,'восстановленные области'):build_mesh_from_bundle_model(m,p)
        m.selected_subchannels={next(k for k,s in m.subchannels.items() if s.sub_type=='interior')}
        self.assertTrue(build_mesh_from_bundle_model(m,p).complete)
    def test_collisions_and_work_limit_do_not_commit_partial_recovery(self):
        m=BundleModel();m.apply_rod_change((0,0),'guide',20.,delete_clashes=False)
        m.active_rod_coord=(-2,0);m.delete_active_rod_manually()
        self.assertFalse(any(s.sub_type=='recovered' for s in m.subchannels.values()));self.assertIn('пересечения',m.recovery_notes[0])
        m=BundleModel();m.active_rod_coord=(0,0)
        with patch('meshbuilder.geometry.recovery.MAX_INTEGRATION_WORK',0):m.delete_active_rod_manually()
        self.assertFalse(any(s.sub_type=='recovered' for s in m.subchannels.values()));self.assertIn('лимит',m.recovery_notes[0])
    def test_circle_polygon_integrals_are_analytic(self):
        for points,area,arc in (([(-3,-2),(-1,-2),(-1,2),(-3,2)],0.,0.),([(1,-2),(3,-2),(3,2),(1,2)],0.,0.),([(-2,-2),(2,-2),(2,2),(-2,2)],math.pi,2*math.pi),([(0,0),(2,0),(2,2),(0,2)],math.pi/4,math.pi/2),([(-2,-2),(0,-2),(0,2),(-2,2)],math.pi/2,math.pi)):
            poly=Polygon(points);self.assertAlmostEqual(circle_area(poly,0,0,1),area,delta=1e-12);self.assertAlmostEqual(wetted_arc(poly,0,0,1),arc,delta=1e-12)
        poly=Polygon([(-2,-2),(2,-2),(2,2),(-2,2)],holes=[[(-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5)]])
        self.assertAlmostEqual(circle_area(poly,0,0,1),math.pi-1,delta=1e-12);self.assertAlmostEqual(wetted_arc(poly,0,0,1),2*math.pi,delta=1e-12)

class RecoveryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def test_recovered_region_is_selectable_and_mesh_limitation_is_explained(self):
        from bundle_subchannel_builder import BundleBuilderWindow
        w=BundleBuilderWindow();self.addCleanup(w.close);self.addCleanup(w.deleteLater)
        w.model.active_rod_coord=(0,0);w.on_delete_rod_manually();w.handle_unified_click(0,0)
        self.assertEqual(w.model.subchannels[w.model.active_sub_id].sub_type,'recovered')
        self.assertIn('Восстановленная',w.inspect_label.text());self.assertIn('восстановлено',w.geometry_status.text())
        with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:w.switch_to_mesh_mode()
        warning.assert_called_once();self.assertEqual(w.left_stack.currentIndex(),0)
    def test_gui_save_load_recovered_selection_then_restore_rods(self):
        import tempfile
        from pathlib import Path
        from bundle_project import capture_project,save_project,load_project,geometry
        from bundle_subchannel_builder import BundleBuilderWindow
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        w.model.active_rod_coord=(0,0);w.on_delete_rod_manually();w.handle_unified_click(0,0)
        expected=geometry(w.model)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'удалённый стержень.json'
            save_project(capture_project(w),path)
            other=BundleBuilderWindow();self.addCleanup(other.deleteLater)
            other.apply_bundle_project(load_project(path))
        self.assertEqual(geometry(other.model),expected)
        self.assertFalse(other.can_export_mesh())
        sid=next(iter(other.model.selected_subchannels))
        self.assertEqual(other.model.subchannels[sid].sub_type,'recovered')
        with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:other.switch_to_mesh_mode()
        warning.assert_called_once()
        other.on_restore_deleted_rods()
        self.assertEqual(len(other.model.rods),19)
        self.assertFalse(other.model.selected_subchannels)
        self.assertFalse(other.model.recovery_notes)
        self.assertEqual(other.model.get_geometry_diagnostics().status,'ok')
