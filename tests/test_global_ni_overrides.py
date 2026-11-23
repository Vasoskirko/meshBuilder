import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow

class GlobalNiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        w.model.selected_subchannels={next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')}
        w.switch_to_mesh_mode()
        return w
    def test_global_default_ni_preserves_local_overrides_and_rebuilds(self):
        w=self.window();p=w.mesh_subpanel
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=2,law='uniform',mode='shape_count')
        tid=p.combo_templates.currentData();gid=p.combo_blocks.currentData()
        w.template_configs[tid]=replace(w.base_params,h1=3e-6)
        w.block_custom_configs[gid]=replace(w.base_params,h1=4e-6)
        p.radio_all.setChecked(True);p.load_active_scope_to_ui()
        p.fields['ni'].setValue(12)
        self.assertEqual(w.base_params.ni,12)
        self.assertEqual(w.template_configs[tid].ni,8)
        self.assertEqual(w.block_custom_configs[gid].ni,8)
        self.assertEqual(w.block_custom_configs[gid].h1,4e-6)
        with patch('bundle_subchannel_builder.QMessageBox.critical') as error:
            w.on_build_multiblock_mesh();error.assert_not_called()
        self.assertTrue(w.can_export_mesh())
    def test_old_mismatch_load_and_all_reset_recover(self):
        w=self.window();p=w.mesh_subpanel
        gid=p.combo_blocks.currentData();tid=p.combo_templates.currentData()
        w.template_configs[tid]=replace(w.base_params,ni=8)
        w.block_custom_configs[gid]=replace(w.base_params,ni=9)
        p.radio_block.setChecked(True)
        self.assertEqual(p.fields['ni'].value(),9)
        self.assertTrue(p.fields['ni'].isEnabled())
        p.on_reset_override()
        self.assertNotIn(gid,w.block_custom_configs)
        p.radio_all.setChecked(True);p.on_reset_override()
        self.assertFalse(w.template_configs);self.assertFalse(w.block_custom_configs)

if __name__=='__main__':unittest.main()
