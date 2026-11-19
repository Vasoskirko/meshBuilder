import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest,tempfile,time,threading
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop,QTimer,QThread
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
from mesh_export_jobs import run_export,ExportCancelled,defer_export_close
from mesh_subchannel import export_subchannel_plot3d
from starccm_export_dialog import StarCcmExportDialog

class ExportJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait_for(self,predicate,timeout=5000):
        loop=QEventLoop();timer=QTimer();timer.setInterval(5)
        def tick():
            if predicate():loop.quit()
        timer.timeout.connect(tick);timer.start();QTimer.singleShot(timeout,loop.quit)
        if not predicate():loop.exec()
        timer.stop();self.assertTrue(predicate(),'Export did not finish')
    def owner(self):
        w=QDialog();w.button=QPushButton('control',w);w.show();self.addCleanup(w.deleteLater);return w
    def mesh(self):
        x,y=np.meshgrid(np.linspace(0,1,50),np.linspace(0,1,35),indexing='ij')
        return SimpleNamespace(complete=True,params=SimpleNamespace(nz=4,z_len=.05),blocks=[(x,y)])
    def test_plot3d_cancel_preserves_target_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mesh.xyz';path.write_text('original')
            calls=[]
            def progress(value,text):
                calls.append(value)
                if len(calls)==3:raise ExportCancelled()
            with self.assertRaises(ExportCancelled):export_subchannel_plot3d(self.mesh(),path,progress_callback=progress)
            self.assertEqual(path.read_text(),'original')
            self.assertEqual([p.name for p in Path(tmp).iterdir()],['mesh.xyz'])
            export_subchannel_plot3d(self.mesh(),path,progress_callback=lambda value,text:calls.append(value))
            self.assertTrue(path.read_text().startswith('1\n'))
            self.assertEqual(calls[-1],97)
    def test_background_export_has_heartbeat_gui_completion_and_restores_controls(self):
        w=self.owner();ready=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        observed=[];done=[];errors=[];beats=[]
        timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:beats.append(1));timer.start();self.addCleanup(timer.stop)
        def compute(progress):
            observed.append(QThread.currentThread()!=self.app.thread());ready.set()
            while not release.wait(.005):progress(30,'Writing blocks')
            return 'saved'
        run_export(w,'test',compute,lambda value:done.append((value,QThread.currentThread()==self.app.thread())),errors.append)
        self.wait_for(ready.is_set);self.wait_for(lambda:len(beats)>=3)
        self.assertFalse(w.button.isEnabled());release.set()
        self.wait_for(lambda:getattr(w,'_export_job',None) is None)
        self.assertEqual(observed,[True]);self.assertEqual(done,[('saved',True)])
        self.assertEqual(errors,[]);self.assertTrue(w.button.isEnabled())
    def test_cancel_error_and_deferred_close_finish_worker(self):
        w=self.owner();errors=[];done=[]
        def compute(progress):
            while True:progress(20,'writing');time.sleep(.003)
        run_export(w,'test',compute,done.append,errors.append)
        self.assertTrue(defer_export_close(w))
        self.wait_for(lambda:getattr(w,'_export_job',None) is None)
        self.assertEqual(done,[]);self.assertIsInstance(errors[0],ExportCancelled)
        self.assertFalse(w.isVisible())
        w.show();errors.clear()
        def broken(progress):raise OSError('disk')
        run_export(w,'test',broken,done.append,errors.append)
        self.wait_for(lambda:getattr(w,'_export_job',None) is None)
        self.assertIsInstance(errors[0],OSError);self.assertTrue(w.button.isEnabled())
    def test_star_export_stages_both_files_and_cancel_keeps_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            macro=Path(tmp)/'setup.java';xyz=Path(tmp)/'bundle_mesh.xyz'
            macro.write_text('old macro');xyz.write_text('old mesh')
            d=StarCcmExportDialog(mesh_result=self.mesh());self.addCleanup(d.deleteLater)
            generated=threading.Event();release=threading.Event();self.addCleanup(release.set)
            def generator(**kwargs):generated.set();release.wait(2);return 'new java'
            d.show()
            with patch('starccm_export_dialog.QFileDialog.getSaveFileName',return_value=(str(macro),'')),patch('starccm_macro_generator.generate_starccm_java_macro',side_effect=generator),patch('starccm_export_dialog.QMessageBox.information') as info,patch('starccm_export_dialog.QMessageBox.critical') as error:
                d.generate_and_save();self.wait_for(generated.is_set)
                # Esc/reject requests cancellation; the active thread survives until completion.
                d.reject();self.assertIsNotNone(d._export_job);release.set()
                self.wait_for(lambda:getattr(d,'_export_job',None) is None)
                self.assertEqual(macro.read_text(),'old macro');self.assertEqual(xyz.read_text(),'old mesh')
                info.assert_not_called();error.assert_not_called()
                self.assertFalse(d.isVisible())
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),['bundle_mesh.xyz','setup.java'])
