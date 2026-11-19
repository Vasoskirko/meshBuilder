import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest,time,threading
from dataclasses import replace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QThread
from PySide6.QtTest import QTest
from bundle_subchannel_builder import BundleBuilderWindow
from bundle_mesh_jobs import analyse_subchannel_result
from bundle_geometry import BundleModel
from mesh_core import MeshParams,controlled_distribution
from mesh_subchannel import build_mesh_from_bundle_model,fill_subchannel_core
import mesh_quality as quality

class ControlledCoreTests(unittest.TestCase):
    def test_first_step_growth_cap_lengths_and_common_count(self):
        length=np.array([.001,.0015,.002]);last=np.array([2e-5,2.5e-5,3e-5])
        d=controlled_distribution(length,last,1.2,1e-4,transition_ratio=1.1)
        np.testing.assert_allclose(d.widths[:,0],last*1.1,rtol=1e-12)
        np.testing.assert_allclose(d.widths.sum(axis=1),length,rtol=1e-12)
        self.assertLessEqual(d.widths.max(),1e-4*(1+1e-12))
        self.assertTrue(np.all(d.widths[:,1:]/d.widths[:,:-1]<=1.2*(1+1e-11)))
        self.assertTrue(np.all(np.diff(d.widths,axis=1)>=-1e-14))
        self.assertEqual(d.widths.shape[1],d.count)
    def test_incompatible_constraints_fail_instead_of_exceeding(self):
        for args in [([1e-4,.01],2e-5,1.1,1e-4),([.001],2e-5,1.1,1e-5),([.001,.0015],2e-5,1.,1e-4)]:
            with self.subTest(args=args),self.assertRaises(ValueError):controlled_distribution(*args)
        d=controlled_distribution([.001,.002],[.0001,.0002],1,.0002)
        self.assertEqual(d.count,10)
    def test_core_preserves_wall_and_quality_topology_matches_detection(self):
        model=BundleModel();sid=next(i for i,s in model.subchannels.items() if s.sub_type=='interior')
        model.selected_subchannels={sid}
        params=MeshParams(ni=8,nj=10,nz=2,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        layer=build_mesh_from_bundle_model(model,params)
        saved=[(x.copy(),y.copy()) for x,y in layer.blocks]
        full=fill_subchannel_core(layer,model,growth=1.2,max_size=.0002,transition_ratio=1.1,core_mode='controlled_growth')
        for (a,b),(x,y),starts in zip(saved,full.blocks,layer.wall_starts):
            xwall=x[:,:a.shape[1]] if starts else x[:,-a.shape[1]:]
            ywall=y[:,:a.shape[1]] if starts else y[:,-a.shape[1]:]
            np.testing.assert_array_equal(a,xwall);np.testing.assert_array_equal(b,ywall)
        explicit=analyse_subchannel_result(full,lambda v,t:None)
        auto=quality.analyse_blocks(quality.blocks_from_result(full))
        self.assertEqual(len(explicit['interfaces']),len(auto['interfaces']))
        for name in auto['metrics']:
            for stat in ('min','max','mean'):
                self.assertAlmostEqual(explicit['metrics'][name][stat],auto['metrics'][name][stat],places=9)

class InteractiveJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.window=BundleBuilderWindow();self.window.show();self.app.processEvents()
        self.messages=patch('bundle_mesh_jobs.QMessageBox.critical');self.error=self.messages.start();self.addCleanup(self.messages.stop)
        self.gate=threading.Event()
    def tearDown(self):
        self.gate.set()
        if getattr(self.window,'_mesh_thread',None) is not None:self.wait(lambda:self.window._mesh_thread is None)
        self.window.close();self.window.deleteLater();self.app.processEvents()
    def wait(self,predicate):
        until=time.monotonic()+8
        while not predicate() and time.monotonic()<until:QTest.qWait(10)
        self.assertTrue(predicate(),'worker did not finish')
    def task(self,progress):
        self.worker_thread=QThread.currentThread();progress(10,'Проверка')
        while not self.gate.wait(.01):progress(20,'Ожидание')
        progress(90,'Завершение');return 42
    def test_worker_keeps_event_loop_live_and_adopts_on_gui_thread(self):
        results=[];ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        self.window._run_mesh_task('test',self.task,lambda value:results.append((value,QThread.currentThread())),'error')
        self.wait(lambda:len(ticks)>=3)
        self.assertEqual(results,[]);self.assertNotEqual(self.worker_thread,self.app.thread())
        self.gate.set();self.wait(lambda:self.window._mesh_thread is None)
        self.assertEqual(results,[(42,self.app.thread())]);self.error.assert_not_called();timer.stop()
    def test_cancel_and_stale_results_are_not_applied(self):
        results=[];self.window._run_mesh_task('test',self.task,results.append,'error')
        self.window._cancel_mesh_job();self.gate.set();self.wait(lambda:self.window._mesh_thread is None)
        self.assertEqual(results,[])
        self.gate.clear();self.window._run_mesh_task('test',self.task,results.append,'error')
        self.window.base_params=replace(self.window.base_params,h1=self.window.base_params.h1*1.1)
        self.gate.set();self.wait(lambda:self.window._mesh_thread is None)
        self.assertEqual(results,[]);self.assertIn('отброшен',self.window.mesh_subpanel.lbl_status.text())
    def test_table_is_on_third_tab_and_mode_available(self):
        w=self.window
        self.assertTrue(w.tabs.widget(2).isAncestorOf(w.table_blocks))
        self.assertFalse(w.tabs.widget(1).isAncestorOf(w.table_blocks))
        self.assertGreaterEqual(w.mesh_subpanel.combo_core_mode.findData('controlled_growth'),0)

    def test_actual_interactive_build_finishes_and_restores_export(self):
        w=self.window
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=5,nz=1)
        w.mesh_subpanel.apply_params(w.base_params)
        w.on_build_multiblock_mesh()
        self.assertIsNotNone(w._mesh_thread)
        self.wait(lambda:w._mesh_thread is None)
        self.error.assert_not_called()
        self.assertIsNotNone(w.current_mesh_result)
        self.assertTrue(w.can_export_mesh())
    def test_close_requests_cancellation_and_waits_for_worker(self):
        results=[];self.window._run_mesh_task('test',self.task,results.append,'error')
        self.window.close();self.assertTrue(self.window._close_after_mesh_job)
        self.gate.set();self.wait(lambda:self.window._mesh_thread is None)
        self.assertEqual(results,[]);self.assertFalse(self.window.isVisible())
    def test_worker_failure_is_reported_without_adopting_result(self):
        results=[]
        def fail(progress):raise ValueError('test failure')
        self.window._run_mesh_task('test',fail,results.append,'error')
        self.wait(lambda:self.window._mesh_thread is None)
        self.assertEqual(results,[]);self.error.assert_called_once()
