import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QMessageBox
from test_local_block_settings import LocalBlockSettingsTests as Helpers
from bundle_project import capture_project

class FullBuildActionTests(unittest.TestCase):
    model=Helpers.model
    window=Helpers.window
    select=Helpers.select
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        for name in ('information','warning','critical','question'):
            mock=patch.object(QMessageBox,name,return_value=QMessageBox.Yes)
            setattr(self,name,mock.start());self.addCleanup(mock.stop)
    def fixed(self,w,count=3):
        p=w.mesh_subpanel
        p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'))
        p.fields['core_layers'].setValue(count)
    def test_full_button_matches_two_steps_and_retains_layer_for_refill(self):
        w=self.window(wall=True);self.fixed(w)
        w.on_build_layer_only();self.assertFalse(w.current_mesh_result.complete)
        w.on_fill_core_clicked();reference=w.current_mesh_result
        w.on_build_multiblock_mesh();self.critical.assert_not_called()
        self.assertTrue(w.current_mesh_result.complete);self.assertTrue(w.can_export_mesh())
        for a,b in zip(reference.blocks,w.current_mesh_result.blocks):
            for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
        layer=w.current_layer_result;self.assertIsNotNone(layer);self.assertFalse(layer.complete)
        w.mesh_subpanel.fields['core_layers'].setValue(4)
        self.assertIs(w.current_layer_result,layer);self.assertFalse(w.can_export_mesh())
        w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
    def test_open_project_then_one_click_builds_local_core_and_ni(self):
        w=self.window(wall=True);self.fixed(w)
        self.select(w.mesh_subpanel,[1]);w.mesh_subpanel.fields['ni'].setValue(12)
        w.mesh_subpanel.fields['core_layers'].setValue(5)
        project=capture_project(w)
        other=self.window();other.apply_bundle_project(project)
        self.assertIsNone(other.current_layer_result)
        other.on_build_multiblock_mesh();self.critical.assert_not_called()
        full=other.current_mesh_result
        self.assertTrue(full.complete)
        self.assertEqual(full.blocks[0][0].shape,(12,10))
        self.assertEqual(full.blocks[1][0].shape,(8,8))
        self.assertTrue(other.can_export_mesh());self.assertEqual(self.question.call_count,1)
    def test_mixed_normal_and_wall_blocks_build_fully_in_one_action(self):
        w=self.window();p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1,local_core_mode='fixed_count',local_core_layers=3)
        w.on_build_multiblock_mesh();self.critical.assert_not_called()
        self.assertTrue(w.current_mesh_result.complete)
        self.assertEqual(w.current_mesh_result.blocks[0][0].shape[1],8)
        self.assertEqual(w.current_mesh_result.blocks[1][0].shape[1],10)
    def test_failed_core_does_not_publish_layer_as_full_mesh(self):
        w=self.window(wall=True);self.fixed(w)
        with patch('bundle_core_groups.fill_with_overrides',side_effect=ValueError('core failure')):
            w.on_build_multiblock_mesh()
        self.critical.assert_called_once();self.assertIsNone(w.current_mesh_result)
        self.assertIsNone(w.current_layer_result);self.assertFalse(w.can_export_mesh())
    def test_normal_distribution_does_not_call_core_filler(self):
        w=self.window()
        with patch('bundle_core_groups.fill_with_overrides') as fill:w.on_build_multiblock_mesh();fill.assert_not_called()
        self.assertTrue(w.current_mesh_result.complete);self.assertIsNone(w.current_layer_result)

del Helpers
if __name__=='__main__':unittest.main()
