"""GUI-safe cancellable file work; hidden callers retain synchronous semantics."""
import threading
import time
from PySide6.QtCore import QObject,QThread,Signal,Slot,Qt,QTimer
from PySide6.QtWidgets import QWidget,QProgressDialog

class ExportCancelled(Exception):pass

class ExportWorker(QObject):
    progress=Signal(int,str)
    finished=Signal(object)
    def __init__(self,compute):
        super().__init__();self.compute=compute;self.cancel=threading.Event()
        self._last_value=None;self._last_emit=0.0
    def report(self,value,text):
        if self.cancel.is_set():raise ExportCancelled()
        now=time.monotonic()
        if value!=self._last_value or now-self._last_emit>=.1:
            self.progress.emit(value,text)
            self._last_value=value;self._last_emit=now
    @Slot()
    def run(self):
        try:outcome=(self.compute(self.report),None)
        except Exception as exc:outcome=(None,exc)
        # No cancellation check after compute: it may have committed files.
        self.finished.emit(outcome)

class ExportJob(QObject):
    def __init__(self,owner,title,compute,success,failure):
        super().__init__(owner)
        self.owner=owner;self.success=success;self.failure=failure;self.outcome=None
        self.pending_close=False;self.started=time.monotonic();self.stage=title
        self.controls=[(w,w.isEnabled()) for w in owner.findChildren(QWidget,options=Qt.FindDirectChildrenOnly)]
        for w,_ in self.controls:w.setEnabled(False)
        self.dialog=QProgressDialog(title,'Отменить',0,100,owner)
        self.dialog.setWindowModality(Qt.NonModal)
        self.dialog.setMinimumDuration(0);self.dialog.setAutoClose(False);self.dialog.setAutoReset(False)
        self.dialog.setValue(0)
        self.thread=QThread(self);self.worker=ExportWorker(compute);self.worker.moveToThread(self.thread)
        self.cancel=self.worker.cancel
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress,Qt.QueuedConnection)
        self.worker.finished.connect(self.receive,Qt.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.complete,Qt.QueuedConnection)
        self.dialog.canceled.connect(self.request_cancel)
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.tick)
    def start(self):self.timer.start();self.thread.start()
    @Slot()
    def request_cancel(self):self.cancel.set();self.stage='Отмена запрошена; ожидание текущей операции'
    @Slot()
    def tick(self):self.dialog.setLabelText(f'{self.stage}\nПрошло {time.monotonic()-self.started:.0f} с.')
    @Slot(int,str)
    def progress(self,value,text):self.stage=text;self.tick();self.dialog.setValue(value)
    @Slot(object)
    def receive(self,outcome):self.outcome=outcome
    @Slot()
    def complete(self):
        self.thread.wait()
        self.timer.stop();self.dialog.canceled.disconnect(self.request_cancel)
        self.dialog.close();self.dialog.deleteLater()
        owner=self.owner;owner._export_job=None
        for widget,enabled in self.controls:widget.setEnabled(enabled)
        result,error=self.outcome
        try:
            if error is None:self.success(result)
            else:self.failure(error)
        finally:
            if self.pending_close:owner.close()
            self.owner=None;self.deleteLater()


def run_export(owner,title,compute,success,failure):
    if getattr(owner,'_export_job',None) is not None:return
    if not owner.isVisible():
        try:result=compute(lambda value,text:None)
        except Exception as exc:failure(exc)
        else:success(result)
        return
    job=ExportJob(owner,title,compute,success,failure)
    owner._export_job=job;job.start()


def defer_export_close(owner):
    job=getattr(owner,'_export_job',None)
    if job is None:return False
    job.pending_close=True;job.request_cancel();return True
