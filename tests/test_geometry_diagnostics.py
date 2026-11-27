"""Coverage is a geometric union check, not a signed sum that cancels errors."""
import csv,math,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from bundle_geometry import BundleModel,Subchannel,RodData
from meshbuilder.geometry.diagnostics import diagnose
from meshbuilder.geometry.hit_test import hit_subchannels

class GeometryDiagnosticsTests(unittest.TestCase):
    def test_complete_sections_and_deleted_rod_gap(self):
        for size in (40.,65.,80.,100.):
            m=BundleModel(s_flat=size);r=m.get_geometry_diagnostics();self.assertEqual(r.status,'ok',r.text())
            self.assertLess(r.gap_upper,r.tolerance);self.assertLess(r.overlap_upper,r.tolerance)
        m=BundleModel();m.active_rod_coord=(0,0);m.delete_active_rod_manually();r=m.get_geometry_diagnostics()
        self.assertEqual(r.status,'error');self.assertGreater(r.gap_lower,290);self.assertLess(r.gap_lower,r.gap_upper)
        self.assertTrue(r.gap_outlines)
    def test_gap_and_overlap_do_not_cancel(self):
        a=Subchannel(1,'interior',[],polygon_points=[(0,0),(6,0),(6,10),(0,10)],a_fluid_mm2=60)
        b=Subchannel(2,'interior',[],polygon_points=[(4,0),(8,0),(8,10),(4,10)],a_fluid_mm2=40)
        model=SimpleNamespace(hex_vertices=[(0,0),(10,0),(10,10),(0,10)],rods={},subchannels={1:a,2:b},normals=[],s_flat=20,pitch=1)
        self.assertEqual(sum(s.a_fluid_mm2 for s in model.subchannels.values()),100)
        r=diagnose(model);self.assertEqual(r.status,'error');self.assertEqual(r.gap_lower,20);self.assertEqual(r.overlap_lower,20)
        self.assertEqual(r.overlap_subchannels,(1,2));self.assertEqual(hit_subchannels(model,5,5),(1,2))
    def test_invalid_polygon_and_unlisted_rod_are_reported(self):
        m=BundleModel();sid=next(iter(m.subchannels));m.subchannels[sid].polygon_points=[(0,0),(2,2),(0,2),(2,0)]
        r=diagnose(m);self.assertIn(sid,r.invalid_subchannels)
        m=BundleModel();sid=next(iter(m.subchannels));x,y=m.subchannels[sid].fluid_center
        m.rods[999]=RodData(999,999,999,x,y,1.)
        self.assertIn(sid,diagnose(m).hydraulic_mismatches)
        m.rods[999].x=m.s_flat
        self.assertIn(999,diagnose(m).wall_collisions)
    def test_cache_is_reused_for_selection_and_invalidated_for_geometry(self):
        m=BundleModel();r=m.get_geometry_diagnostics();m.select_all_subchannels()
        self.assertIs(m.get_geometry_diagnostics(),r);self.assertIs(deepcopy(r),r)
        m.apply_rod_change((0,0),'guide',10.);self.assertIsNot(m.get_geometry_diagnostics(),r)
    def test_every_valid_label_point_picks_its_own_region(self):
        m=BundleModel()
        for sid,(x,y) in m.get_geometry_diagnostics().label_points:self.assertEqual(hit_subchannels(m,x,y),(sid,))
        m.active_rod_coord=(0,0);m.delete_active_rod_manually();self.assertEqual(hit_subchannels(m,0,0),())
    def test_circle_bounds_tighten_and_cover_physical_gap(self):
        m=BundleModel();m.active_rod_coord=(0,0);m.delete_active_rod_manually()
        coarse=diagnose(m,8);fine=diagnose(m,64)
        self.assertLessEqual(coarse.gap_lower,fine.gap_lower+1e-8);self.assertGreaterEqual(coarse.gap_upper,fine.gap_upper-1e-8)
        self.assertLess(fine.gap_upper-fine.gap_lower,coarse.gap_upper-coarse.gap_lower)
    def test_hydraulics_and_json_keep_full_precision(self):
        m=BundleModel();s=next(s for s in m.subchannels.values() if s.sub_type=='interior')
        exact=math.sqrt(3)*m.pitch**2/4-math.pi*m.d_fuel**2/8
        self.assertAlmostEqual(s.a_fluid_mm2,exact,delta=1e-11)
        m.selected_subchannels={s.sub_id};self.assertEqual(m.get_selection_summary()['total_a_fluid_mm2'],s.a_fluid_mm2)
        self.assertEqual(m.export_dict()['subchannels'][0]['a_fluid_mm2'],s.a_fluid_mm2)

class GeometryDiagnosticsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def window(self):
        from bundle_subchannel_builder import BundleBuilderWindow
        w=BundleBuilderWindow();self.addCleanup(w.close);self.addCleanup(w.deleteLater);return w
    def test_missing_coverage_is_visible_and_pick_does_not_jump_across_gap(self):
        w=self.window();w.model.active_rod_coord=(0,0);w.on_delete_rod_manually()
        self.assertIn('Есть проблемы',w.geometry_status.text());self.assertIn('не подтверждена',w.summary_text.text())
        w.geometry_show_problems.setChecked(True);self.assertTrue(w.ax.lines)
        w.handle_unified_click(0,0);self.assertFalse(w.model.selected_subchannels)
    def test_missing_dependency_is_not_reported_as_valid_geometry(self):
        w=self.window()
        with patch.object(w.model,'get_geometry_diagnostics',side_effect=ImportError):w.rebuild_view()
        self.assertIn('недоступна',w.geometry_status.text());self.assertIn('не подтверждена',w.summary_text.text())
    def test_csv_uses_model_values_not_rounded_table_text(self):
        from bundle_hydraulics_dialog import HydraulicsTableDialog
        w=self.window();dialog=HydraulicsTableDialog(w,w.model);self.addCleanup(dialog.deleteLater)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'hyd.csv'
            with patch('bundle_hydraulics_dialog.QFileDialog.getSaveFileName',return_value=(str(path),'CSV')),patch('bundle_hydraulics_dialog.QMessageBox.information'):
                dialog.export_csv()
            with path.open(encoding='utf-8-sig') as stream:rows=list(csv.reader(stream))
            for row in rows[1:]:self.assertEqual(float(row[3]),w.model.subchannels[int(row[0][1:])].a_fluid_mm2)
    def test_large_diagnostics_uses_worker_and_reuses_report(self):
        import time
        from PySide6.QtTest import QTest
        from meshbuilder.geometry.diagnostics import diagnose as real_diagnose
        w=self.window();w.show();self.app.processEvents();w.model._diagnostics_cache=None
        def delayed(model,**kwargs):
            kwargs['progress'](2,'Проверка');time.sleep(.08);return real_diagnose(model,**kwargs)
        with patch('meshbuilder.geometry.ui.AUTO_DIAGNOSTIC_LIMIT',0),patch.object(w,'mesh_inputs',side_effect=ValueError('draft')),patch('meshbuilder.geometry.ui.QMessageBox.warning') as warning:
            w.geometry_check_button.click();warning.assert_called_once();self.assertIsNone(getattr(w,'_mesh_thread',None))
        with patch('meshbuilder.geometry.ui.AUTO_DIAGNOSTIC_LIMIT',0),patch('meshbuilder.geometry.diagnostics.diagnose',side_effect=delayed),patch('meshbuilder.geometry.ui.QMessageBox.information'):
            w.rebuild_view();self.assertIn('ещё не выполнена',w.geometry_status.text())
            w.geometry_check_button.click();self.assertIsNotNone(w._mesh_thread)
            start=time.monotonic()
            while w._mesh_thread is not None and time.monotonic()-start<10:QTest.qWait(10)
            self.assertIsNone(w._mesh_thread);self.assertIsNotNone(w.model._diagnostics_cache)
            self.assertEqual(w.model.get_geometry_diagnostics().status,'ok')
    def test_package_and_legacy_api_are_the_same_classes(self):
        from meshbuilder.geometry import BundleModel as NewModel,Subchannel as NewSubchannel
        import importlib
        self.assertIs(NewModel,BundleModel);self.assertIs(NewSubchannel,Subchannel)
        for name in ('lattice','subchannels','hydraulics','selection','edits','collisions','export','validation','diagnostics','hit_test'):
            importlib.import_module('meshbuilder.geometry.'+name)
    def test_clicking_fluid_switches_inspector_from_rod_to_subchannel(self):
        w=self.window();w.model.active_rod_coord=(0,0);w.update_inspector()
        sid,point=w.model.get_geometry_diagnostics().label_points[0]
        w.handle_unified_click(*point)
        self.assertIsNone(w.model.active_rod_coord);self.assertEqual(w.model.active_sub_id,sid)
        self.assertTrue(w.rod_controls.isHidden());self.assertIn('подканал S'+str(sid),w.inspect_label.text())
