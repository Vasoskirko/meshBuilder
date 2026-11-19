import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_core_smoothing import smooth_core
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model,fill_subchannel_core,_validate_interfaces
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow

class CoreSmoothingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_perturbed_patch_improves_with_perimeter_and_first_step_fixed(self):
        x,y=np.meshgrid(np.linspace(0,1,12),np.linspace(0,1,15),indexing='ij')
        grid=np.stack((x,y),axis=-1)
        grid[4:8,4:10,0]+=.035*np.sin(np.linspace(0,np.pi,6))[None,:]
        original=grid.copy();after,info=smooth_core(grid,15)
        np.testing.assert_array_equal(grid,original)
        for a,b in [(after[0],original[0]),(after[-1],original[-1]),(after[:,:2],original[:,:2]),(after[:,-1],original[:,-1])]:
            np.testing.assert_array_equal(a,b)
        self.assertGreater(info['accepted_steps'],0)
        self.assertGreater(info['after']['min_scaled_jacobian'],info['before']['min_scaled_jacobian'])
        self.assertLess(info['after']['mean_angle_error_deg'],info['before']['mean_angle_error_deg'])
        flipped,fi=smooth_core(grid[:,::-1],15)
        self.assertGreater(fi['after']['min_scaled_jacobian'],0)
    def test_bundle_comparison_preserves_layer_interfaces_and_real_widths(self):
        m=BundleModel();ids=[i for i,s in m.subchannels.items() if s.sub_type=='interior']
        m.selected_subchannels={ids[0],next(i for i in ids[1:] if len(set(m.subchannels[ids[0]].rod_ids)&set(m.subchannels[i].rod_ids))==2)}
        p=MeshParams(ni=12,nj=20,nz=2,law='wall_core',mode='layer_first_growth',wall_layers=5,h1=5e-6,layer_growth=1.1)
        layer=build_mesh_from_bundle_model(m,p)
        plain=fill_subchannel_core(layer,m,core_mode='fixed_count',core_layers=15)
        result=fill_subchannel_core(layer,m,core_mode='fixed_count',core_layers=15,smoothing_iterations=15)
        self.assertEqual(len(result.comparison_blocks),len(result.blocks))
        _validate_interfaces(result.blocks,result.interfaces,p.pitch*1e-11)
        for i,((x,y),(oldx,oldy),starts) in enumerate(zip(result.blocks,layer.blocks,layer.wall_starts)):
            count=oldx.shape[1]
            np.testing.assert_array_equal(result.comparison_blocks[i][0],plain.blocks[i][0])
            np.testing.assert_array_equal(x[:,:count] if starts else x[:,-count:],oldx)
            np.testing.assert_array_equal(y[:,:count] if starts else y[:,-count:],oldy)
            pts=np.stack((x,y),axis=-1)
            core=pts[:,count-1:] if starts else pts[:,:-(count-1)][:,::-1]
            np.testing.assert_allclose(result.all_block_widths[i][:,count-1:],np.linalg.norm(np.diff(core,axis=1),axis=-1),rtol=1e-12)
        q=result.diagnostics['core_smoothing']
        self.assertGreaterEqual(q['after_min_scaled_jacobian'],q['before_min_scaled_jacobian']-1e-12)
        self.assertLessEqual(q['after_mean_angle_error_deg'],q['before_mean_angle_error_deg'])
        strict=fill_subchannel_core(layer,m,core_mode='controlled_growth',growth=1.2,max_size=.0002,smoothing_iterations=10)
        self.assertLessEqual(strict.diagnostics['core_step_max_m'],.0002*(1+1e-10))
        self.assertEqual(plain.comparison_blocks,[])
    def test_switch_invalidates_full_mesh_and_keeps_layer(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=1,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        w.mesh_subpanel.apply_params(w.base_params)
        with patch.object(w,'redraw_mesh_views'),patch.object(w,'populate_blocks_table'),patch('bundle_subchannel_builder.QMessageBox.information'):
            w.on_build_layer_only();layer=w.current_layer_result
            w.mesh_subpanel.combo_core_mode.setCurrentIndex(w.mesh_subpanel.combo_core_mode.findData('fixed_count'))
            w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
            w.mesh_subpanel.chk_smooth_core.setChecked(True)
            self.assertIs(w.current_layer_result,layer);self.assertFalse(w.can_export_mesh())
            w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
        w.redraw_mesh_views()
        self.assertTrue(w.chk_compare_core.isEnabled())
        self.assertIn('Сглаживание',w.mesh_subpanel.lbl_status.text())
        self.assertTrue(any('До сглаживания' in line.get_label() for line in w.ax_layers.lines))
