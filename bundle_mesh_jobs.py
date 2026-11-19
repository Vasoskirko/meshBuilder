"""Run interactive mesh work off the GUI thread with cooperative stage cancellation."""
import threading
import time
from PySide6.QtCore import QObject,QThread,Signal,Slot,Qt,QTimer
from PySide6.QtWidgets import QProgressDialog,QMessageBox

class MeshTaskCancelled(Exception):pass

class MeshWorker(QObject):
    progress=Signal(int,str)
    finished=Signal(object)
    def __init__(self,compute):
        super().__init__();self.compute=compute;self.cancelled=threading.Event()
    def report(self,value,text):
        if self.cancelled.is_set():raise MeshTaskCancelled()
        self.progress.emit(value,text)
    @Slot()
    def run(self):
        try:
            result=self.compute(self.report)
            self.report(98,'Подготовка отображения')
            outcome=(result,None)
        except Exception as exc:outcome=(None,exc)
        self.finished.emit(outcome)

class MeshJobController(QObject):
    """Real QObject receiver: mixin slots alone do not guarantee Qt affinity."""
    def __init__(self,owner):super().__init__(owner);self.owner=owner
    @Slot(int,str)
    def progress(self,value,text):self.owner._mesh_job_progress(value,text)
    @Slot(object)
    def receive(self,outcome):self.owner._mesh_job_received(outcome)
    @Slot()
    def complete(self):
        owner=self.owner
        owner._mesh_thread.wait()  # finished signal can precede TLS cleanup
        owner._mesh_job_finished()
        owner._mesh_controller=None
        self.owner=None
        self.deleteLater()

class BundleMeshJobsMixin:
    def _run_mesh_task(self,title,compute,completed,error_title):
        if getattr(self,'_mesh_thread',None) is not None:return
        # Hidden/programmatic windows retain their synchronous calling contract.
        # Interactive windows always use the worker; no QWidget is touched there.
        if not self.isVisible():
            result=compute(lambda value,text:None);completed(result);return
        captured=self.mesh_inputs()
        thread=QThread(self);worker=MeshWorker(compute);worker.moveToThread(thread)
        dialog=QProgressDialog(title,'Отменить',0,100,self)
        dialog.setWindowModality(Qt.WindowModal);dialog.setMinimumDuration(0)
        dialog.setAutoClose(False);dialog.setAutoReset(False)
        dialog.setValue(0)
        self._mesh_thread=thread;self._mesh_worker=worker;self._mesh_cancel=worker.cancelled;self._mesh_progress=dialog
        self._mesh_job_result=None;self._mesh_completion=completed
        self._mesh_job_inputs=captured;self._mesh_error_title=error_title
        controller=MeshJobController(self)
        self._mesh_controller=controller
        thread.started.connect(worker.run)
        worker.progress.connect(controller.progress,Qt.QueuedConnection)
        worker.finished.connect(controller.receive,Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(controller.complete,Qt.QueuedConnection)
        thread.finished.connect(thread.deleteLater)
        dialog.canceled.connect(self._cancel_mesh_job)
        self._mesh_stage=title;self._mesh_started=time.monotonic()
        self._mesh_timer=QTimer(self);self._mesh_timer.setInterval(250)
        self._mesh_timer.timeout.connect(self._mesh_job_elapsed);self._mesh_timer.start()
        thread.start()

    @Slot(int,str)
    def _mesh_job_progress(self,value,text):
        if self._mesh_thread is None:return
        self._mesh_stage=text
        self._mesh_job_elapsed();self._mesh_progress.setValue(value)

    @Slot(object)
    def _mesh_job_received(self,outcome):self._mesh_job_result=outcome

    def _mesh_job_elapsed(self):
        if self._mesh_thread is None:return
        self._mesh_progress.setLabelText(f'{self._mesh_stage}\nПрошло {time.monotonic()-self._mesh_started:.0f} с. Отмена выполняется между блоками/этапами.')

    def _cancel_mesh_job(self):
        if self._mesh_thread is None:return
        self._mesh_cancel.set()
        self.mesh_subpanel.lbl_status.setText('Отмена запрошена; ожидание завершения текущего этапа…')

    @Slot()
    def _mesh_job_finished(self):
        outcome=self._mesh_job_result
        cancelled=self._mesh_cancel.is_set()
        self._mesh_timer.stop();self._mesh_timer.deleteLater()
        dialog=self._mesh_progress
        self._mesh_thread=None;self._mesh_worker=None
        dialog.canceled.disconnect(self._cancel_mesh_job)
        dialog.close();dialog.deleteLater()
        if outcome is not None and not cancelled:
            result,error=outcome
            if error is not None:
                from mesh_advisor import format_friendly_error
                QMessageBox.critical(self,self._mesh_error_title,format_friendly_error(error))
            else:
                try:
                    if self.mesh_inputs()!=self._mesh_job_inputs:
                        self.mesh_subpanel.lbl_status.setText('Параметры изменились; результат построения отброшен.')
                    else:self._mesh_completion(result)
                except Exception as exc:
                    QMessageBox.critical(self,self._mesh_error_title,str(exc))
        else:self.mesh_subpanel.lbl_status.setText('Построение отменено. Новый результат не применяется.')
        self._mesh_completion=None;self._mesh_job_result=None
        if getattr(self,'_close_after_mesh_job',False):self.close()

    def closeEvent(self,event):
        if getattr(self,'_mesh_thread',None) is not None:
            self._close_after_mesh_job=True;self._cancel_mesh_job();event.ignore();return
        super().closeEvent(event)


def analyse_subchannel_result(result, progress):
    """Reuse validated builder topology instead of detecting 3D face pairs again."""
    import numpy as np
    import mesh_quality as quality
    z=np.linspace(0,result.params.z_len,result.params.nz+1)
    blocks=[]
    for n,block in enumerate(result.blocks):
        progress(55+int(10*n/len(result.blocks)),f'3D-блок {n+1}/{len(result.blocks)}')
        blocks.extend(quality.extrude_blocks([block],z))
    interfaces=[(it.block_a,it.face_a,it.block_b,it.face_b,it.reversed)
        for it in result.interfaces if result.complete or not it.face_a.startswith('j_')]
    return quality.analyse_blocks(blocks,interfaces=interfaces,
        progress_callback=lambda fraction,text:progress(65+int(27*fraction),text))
