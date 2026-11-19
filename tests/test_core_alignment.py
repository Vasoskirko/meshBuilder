import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_core_alignment import aligned_distribution
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model,fill_subchannel_core,_validate_interfaces
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow

class CoreAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_count_targets_local_aspect_and_preserves_hard_constraints(self):
        lengths=np.ones(4);first=np.full(4,.01);tangent=np.tile([.02,0.],(4,1))
        d,info=aligned_distribution(lengths,first,tangent,tangent,1.5,.2,200)
        self.assertLess(info['score'],info['baseline_score'])
        self.assertLess(abs(d.plateau[0]/.02-1),.1)
        np.testing.assert_allclose(d.widths.sum(axis=1),lengths,rtol=1e-12)
        np.testing.assert_allclose(d.widths[:,0],first,rtol=1e-12)
        self.assertLessEqual(d.widths.max(),.2*(1+1e-10))
        ratios=d.widths[:,1:]/d.widths[:,:-1]
        self.assertGreaterEqual(ratios.min(),1-1e-10)
        self.assertLessEqual(ratios.max(),1.5*(1+1e-10))
        # Smaller tangential size must influence the selected common count.
        finer,_=aligned_distribution(lengths,first,tangent/2,tangent/2,1.5,.2,200)
        self.assertGreater(finer.count,d.count)
        with self.assertRaises(ValueError):
            aligned_distribution(lengths,first,tangent,tangent,1.1,.001,200)

    def test_neighbors_and_wall_preserved_default_unchanged(self):
        m=BundleModel();ids=[i for i,s in m.subchannels.items() if s.sub_type=='interior']
        m.selected_subchannels={ids[0],next(i for i in ids[1:] if len(set(m.subchannels[ids[0]].rod_ids)&set(m.subchannels[i].rod_ids))==2)}
        p=MeshParams(ni=12,nj=20,nz=2,law='wall_core',mode='layer_first_growth',wall_layers=5,h1=5e-6,layer_growth=1.1)
        layer=build_mesh_from_bundle_model(m,p)
        plain=fill_subchannel_core(layer,m)
        result=fill_subchannel_core(layer,m,align_core=True,growth=1.2,max_size=.0002)
        self.assertNotIn('core_alignment',plain.diagnostics)
        _validate_interfaces(result.blocks,result.interfaces,p.pitch*1e-11)
        for i,((x,y),(oldx,oldy),starts) in enumerate(zip(result.blocks,layer.blocks,layer.wall_starts)):
            count=oldx.shape[1]
            np.testing.assert_array_equal(x[:,:count] if starts else x[:,-count:],oldx)
            np.testing.assert_array_equal(y[:,:count] if starts else y[:,-count:],oldy)
            widths=result.all_block_widths[i][:,count-1:]
            np.testing.assert_allclose(widths[:,0],layer.all_block_widths[i][:,-1],rtol=1e-10)
            self.assertLessEqual(widths.max(),.0002*(1+1e-9))
        self.assertLessEqual(result.diagnostics['core_alignment']['score'],result.diagnostics['core_alignment']['baseline_score']+1e-10)
        self.assertTrue(np.isfinite(result.diagnostics['core_alignment']['p95']))
        hermite=fill_subchannel_core(layer,m,align_core=True,growth=1.2,max_size=.0002,hermite_tfi=True)
        for (x,y),(xx,yy) in zip(result.blocks,hermite.blocks):
            np.testing.assert_array_equal(x,xx);np.testing.assert_array_equal(y,yy)
        again=fill_subchannel_core(layer,m)
        for (x,y),(xx,yy) in zip(plain.blocks,again.blocks):
            np.testing.assert_array_equal(x,xx);np.testing.assert_array_equal(y,yy)

    def test_switch_invalidates_full_only_and_export_restored(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=1,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        w.mesh_subpanel.apply_params(w.base_params)
        w.mesh_subpanel.fields['core_growth'].setValue(1.2)
        w.mesh_subpanel.fields['core_max_size'].setValue(.0002)
        self.assertFalse(w.mesh_subpanel.chk_align_core.isChecked())
        with patch.object(w,'redraw_mesh_views'),patch.object(w,'populate_blocks_table'),patch('bundle_subchannel_builder.QMessageBox.information'),patch('bundle_subchannel_builder.QMessageBox.critical',side_effect=AssertionError('Unexpected build failure')):
            w.on_build_layer_only();layer=w.current_layer_result
            w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
            w.mesh_subpanel.chk_align_core.setChecked(True)
            self.assertIs(w.current_layer_result,layer);self.assertFalse(w.can_export_mesh())
            self.assertFalse(w.mesh_subpanel.combo_core_mode.isEnabled())
            with patch('bundle_subchannel_builder.QMessageBox.warning') as warning,patch('bundle_subchannel_builder.QFileDialog.getSaveFileName',return_value=('', '')) as save,patch('starccm_export_dialog.StarCcmExportDialog') as star:
                w.on_export_plot3d();w.on_export_starccm_dialog()
                self.assertEqual(warning.call_count,2);save.assert_not_called();star.assert_not_called()
                w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
                w.on_export_plot3d();w.on_export_starccm_dialog()
                save.assert_called_once();star.return_value.exec.assert_called_once()
            self.assertIn('Выравнивание ядра',w.mesh_subpanel.lbl_status.text())
            w.mesh_subpanel.chk_align_core.setChecked(False)
            self.assertIs(w.current_layer_result,layer);self.assertFalse(w.can_export_mesh())
            self.assertTrue(w.mesh_subpanel.combo_core_mode.isEnabled())
            w.on_fill_core_clicked();self.assertTrue(w.can_export_mesh())
