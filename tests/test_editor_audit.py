import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from test_local_block_settings import LocalBlockSettingsTests as Helpers

class EditorAuditTests(unittest.TestCase):
    model=Helpers.model
    window=Helpers.window
    select=Helpers.select
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        mock=patch('sys.excepthook');self.qt_errors=mock.start();self.addCleanup(mock.stop)
        for method in ('information','warning','critical'):
            mock=patch.object(QMessageBox,method);mock.start();self.addCleanup(mock.stop)
        mock=patch.object(QMessageBox,'question',return_value=QMessageBox.Yes);mock.start();self.addCleanup(mock.stop)
    def tearDown(self):self.qt_errors.assert_not_called()
    def type_spin(self,widget,text):
        widget.lineEdit().setText(text)
        widget.lineEdit().textEdited.emit(text)
        widget.interpretText()
        widget.editingFinished.emit()
    def test_mixed_integer_accepts_value_equal_to_first_block(self):
        w=self.window();p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,ni=8)
        w.block_custom_configs[2]=replace(w.base_params,ni=12)
        self.select(p,[1,2]);self.type_spin(p.fields['ni'],'8')
        self.assertEqual([w.block_custom_configs[k].ni for k in (1,2)],[8,8])
    def test_mixed_first_step_accepts_value_equal_to_first_block(self):
        w=self.window();p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,h1=3e-6)
        w.block_custom_configs[2]=replace(w.base_params,h1=4e-6)
        self.select(p,[1,2]);field=p.fields['h1'];field.setText('3');field.edited.emit()
        self.assertEqual([w.block_custom_configs[k].h1 for k in (1,2)],[3e-6,3e-6])
    def test_mixed_core_count_accepts_first_value_without_touching_wall(self):
        w=self.window(wall=True);p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,local_core_mode='fixed_count',local_core_layers=3)
        w.block_custom_configs[2]=replace(w.base_params,local_core_mode='fixed_count',local_core_layers=5)
        self.select(p,[1,2]);self.type_spin(p.fields['core_layers'],'3')
        self.assertEqual([w.block_custom_configs[k].local_core_layers for k in (1,2)],[3,3])
    def test_same_mode_can_be_applied_to_mixed_selection(self):
        w=self.window();p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,mode='first_count')
        w.block_custom_configs[2]=replace(w.base_params,mode='first_max')
        self.select(p,[1,2]);p.goal.activated.emit(p.goal.currentIndex())
        self.assertEqual([w.block_custom_configs[k].mode for k in (1,2)],['first_count','first_count'])
    def test_invalid_core_signal_preserves_layer_and_blocks_export(self):
        for local in (False,True):
            w=self.window(wall=True);p=w.mesh_subpanel
            w.on_build_layer_only();layer=w.current_layer_result
            if local:self.select(p,[1])
            p.fields['core_growth'].setText('invalid')
            p.fields['core_growth'].edited.emit()
            self.assertIs(w.current_layer_result,layer)
            self.assertIsNone(w.current_mesh_result)
            self.assertFalse(w.can_export_mesh())
            p.fields['core_growth'].setText('1.2');p.fields['core_growth'].edited.emit()
            self.assertIs(w.current_layer_result,layer)
            w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
    def test_direct_export_detects_uncommitted_wall_and_local_core_drafts(self):
        w=self.window();p=w.mesh_subpanel;w.on_build_multiblock_mesh()
        p.fields['h1'].setText('7')
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName') as chooser:
            w.on_export_plot3d();chooser.assert_not_called()
        self.assertFalse(w.can_export_mesh())
        w=self.window(wall=True);p=w.mesh_subpanel
        w.on_build_layer_only();p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'))
        w.on_fill_core_clicked();layer=w.current_layer_result
        self.select(p,[1]);p.fields['core_layers'].lineEdit().setText('7')
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName') as chooser:
            w.on_export_plot3d();chooser.assert_not_called()
        self.assertIs(w.current_layer_result,layer)
        self.assertFalse(w.can_export_mesh())

del Helpers

if __name__=='__main__':unittest.main()
