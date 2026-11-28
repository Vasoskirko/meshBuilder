import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QApplication,QMessageBox
from bundle_geometry import BundleModel
from mesh_core import MeshParams
import mesh_subchannel as ms
from mesh_interface_diagnostics import require_star_conformity,partition_interfaces
from bundle_subchannel_builder import BundleBuilderWindow
from bundle_project import capture_project,save_project,load_project
from bundle_local_core import settings
from bundle_mesh_preview import forecast

class LocalBlockSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        mock=patch.object(QMessageBox,'information');mock.start();self.addCleanup(mock.stop)
    def model(self):
        m=BundleModel();m.selected_subchannels={next(i for i,s in m.subchannels.items() if s.sub_type=='interior')};return m
    def window(self,wall=False):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater);w.model=self.model();w.switch_to_mesh_mode()
        w.base_params=MeshParams(ni=8,nj=10,nz=2)
        if wall:w.base_params=replace(w.base_params,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        w.mesh_subpanel.load_active_scope_to_ui();return w
    def select(self,p,ids):
        with QSignalBlocker(p.tree_blocks):
            p.tree_blocks.clearSelection()
            for item in p.tree_blocks.findItems('',Qt.MatchContains|Qt.MatchRecursive,0):
                if item.data(0,Qt.UserRole) and item.data(0,Qt.UserRole)[0]=='block':item.setSelected(item.data(0,Qt.UserRole)[1] in ids)
        from bundle_block_editor import selected
        selected(p)
    def test_batch_edits_only_changed_fields_and_shows_mixed(self):
        w=self.window();p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,ni=9,h1=3e-6)
        w.block_custom_configs[2]=replace(w.base_params,ni=11,h1=4e-6)
        self.select(p,[1,2])
        self.app.processEvents()
        self.assertEqual(p.fields['ni'].lineEdit().text(),'Разные значения')
        p.fields['ni'].setValue(13)
        self.assertEqual([w.block_custom_configs[k].ni for k in (1,2)],[13,13])
        self.assertEqual([w.block_custom_configs[k].h1 for k in (1,2)],[3e-6,4e-6])
        self.assertEqual(w.base_params.ni,8)
        w.block_custom_configs[3]=replace(w.base_params,max_auto_cells=7000,filename='keep.xyz')
        self.select(p,[3]);p.fields['ni'].setValue(15)
        self.assertEqual(w.block_custom_configs[3].max_auto_cells,7000)
        self.assertEqual(w.block_custom_configs[3].filename,'keep.xyz')
        self.assertEqual(w.block_custom_configs[1].ni,13);self.assertEqual(w.block_custom_configs[3].ni,15)
    def test_nonconformal_build_confirm_highlight_plot3d_and_star_guard(self):
        w=self.window();p=w.mesh_subpanel;self.select(p,[1]);p.fields['ni'].setValue(12)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as question,patch.object(QMessageBox,'critical') as error:
            w.on_build_multiblock_mesh();error.assert_not_called();question.assert_called_once()
        r=w.current_mesh_result
        self.assertTrue(r.complete);self.assertTrue(r.diagnostics['interface_problems'])
        self.assertTrue(all(i['kind']=='nonconformal' for i in r.diagnostics['interface_problems']))
        self.assertTrue(w.can_export_mesh())
        with self.assertRaises(ValueError):require_star_conformity(r)
        with patch.object(QMessageBox,'warning') as warning,patch('starccm_export_dialog.StarCcmExportDialog') as dialog:
            w.on_export_starccm_dialog();warning.assert_called_once();dialog.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:ms.export_subchannel_plot3d(r,Path(tmp)/'preview.xyz')
        self.assertFalse(p.btn_export_star.isEnabled())
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No):
            p.fields['ni'].setValue(14);w.on_build_multiblock_mesh()
        self.assertFalse(w.can_export_mesh())
    def test_local_core_preserves_wall_and_refills_different_counts(self):
        w=self.window(wall=True);p=w.mesh_subpanel
        with patch.object(QMessageBox,'critical') as error:w.on_build_layer_only();error.assert_not_called()
        layer=w.current_layer_result
        p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'));p.fields['core_layers'].setValue(3)
        self.select(p,[1]);p.fields['core_layers'].setValue(5)
        self.assertIs(w.current_layer_result,layer)
        self.assertEqual(w.block_custom_configs[1].local_core_layers,5)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QMessageBox,'critical') as error:
            w.on_fill_core_clicked();error.assert_not_called()
        full=w.current_mesh_result
        self.assertTrue(full.complete)
        self.assertEqual(full.blocks[0][0].shape[1],10) # four wall + five core + node
        self.assertEqual(full.blocks[1][0].shape[1],8)
        np.testing.assert_array_equal(full.blocks[0][0][:,:5],layer.blocks[0][0])
        self.assertTrue(full.diagnostics['interface_problems'])
        saved=capture_project(w)
        self.assertEqual(saved.blocks[1].local_core_layers,5)
        self.assertEqual(saved.data['mesh']['core']['core_layers'],3)
    def test_local_ni_and_core_project_roundtrip_and_layer_with_different_ni(self):
        w=self.window(wall=True);p=w.mesh_subpanel
        self.select(p,[1]);p.fields['ni'].setValue(12)
        p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'));p.fields['core_layers'].setValue(5)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'project.json';save_project(capture_project(w),path);project=load_project(path)
        self.assertEqual(project.blocks[1].ni,12);self.assertEqual(project.blocks[1].local_core_layers,5)
        other=self.window();other.apply_bundle_project(project)
        self.assertEqual(other.block_custom_configs[1].ni,12)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QMessageBox,'critical') as error:
            other.on_build_layer_only();other.on_fill_core_clicked();error.assert_not_called()
        self.assertTrue(other.current_mesh_result.complete)
        self.assertEqual(other.current_mesh_result.blocks[0][0].shape[0],12)
    def test_local_core_forecast_and_old_project_migration(self):
        from bundle_local_core import DEFAULTS
        m=self.model();p=MeshParams(ni=8,nj=10,nz=2,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        overrides={1:replace(p,ni=12,local_core_mode='fixed_count',local_core_layers=5)}
        layer=ms.build_mesh_from_bundle_model(m,p,block_custom_overrides=overrides,allow_nonconformal=True)
        core=dict(mode='fixed_count',growth=1.1,size=.00012,limit=5000,layers=3,transition=1.1)
        data=forecast(m,p,{},overrides,core,layer)
        full=ms.fill_subchannel_core(layer,m,core_mode='fixed_count',core_layers=3,allow_nonconformal=True,core_overrides={0:settings(overrides[1])})
        self.assertEqual(data['full']['cells'],(full.diagnostics['cells_3d'],)*2)
        w=self.window();project=capture_project(w).data;project['version']=1
        for key in DEFAULTS:project['mesh']['base'].pop(key)
        from bundle_project import validate_project
        migrated=validate_project(project)
        self.assertEqual(migrated.data['version'],2);self.assertEqual(migrated.base.local_core_mode,'inherit')
    def test_batch_core_change_retains_other_local_fields(self):
        w=self.window(wall=True);p=w.mesh_subpanel
        w.block_custom_configs[1]=replace(w.base_params,local_core_mode='fixed_count',local_core_layers=3,local_core_transition=1.1)
        w.block_custom_configs[2]=replace(w.base_params,local_core_mode='fixed_count',local_core_layers=5,local_core_transition=1.2)
        self.select(p,[1,2]);self.app.processEvents()
        self.assertEqual(p.fields['core_layers'].lineEdit().text(),'Разные значения')
        p.fields['core_layers'].setValue(7)
        self.assertEqual([w.block_custom_configs[k].local_core_layers for k in (1,2)],[7,7])
        self.assertEqual([w.block_custom_configs[k].local_core_transition for k in (1,2)],[1.1,1.2])
    def test_mixed_full_blocks_and_wall_layers_can_be_filled(self):
        m=self.model();p=MeshParams(ni=8,nj=10,nz=2)
        wall=replace(p,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        layer=ms.build_mesh_from_bundle_model(m,p,block_custom_overrides={1:wall},allow_nonconformal=True)
        self.assertFalse(layer.complete)
        full=ms.fill_subchannel_core(layer,m,core_mode='fixed_count',core_layers=3,allow_nonconformal=True)
        self.assertTrue(full.complete)
        np.testing.assert_array_equal(full.blocks[1][0],layer.blocks[1][0])
        self.assertEqual(full.blocks[0][0].shape[1],8)
    def test_canvas_ctrl_selection_and_independent_core_inheritance(self):
        from types import SimpleNamespace
        from bundle_block_editor import effective_core
        w=self.window();p=w.mesh_subpanel
        with patch.object(QMessageBox,'critical') as error:w.on_build_multiblock_mesh();error.assert_not_called()
        for i,key in ((0,None),(1,'control')):
            x,y=w.current_mesh_result.blocks[i]
            event=SimpleNamespace(inaxes=w.ax_mesh,button=1,key=key,xdata=float(x.mean()*1e3),ydata=float(y.mean()*1e3))
            w.on_select_mesh_block(event)
        self.assertEqual(p.selected_block_ids(),[1,2])
        tid=w.get_template_for_block(1)
        w.template_configs[tid]=replace(w.base_params,local_core_mode='fixed_count',local_core_layers=9)
        w.block_custom_configs[1]=replace(w.base_params,h1=3e-6)
        self.assertEqual(effective_core(p,1)['local_core_layers'],9)
    def test_refill_audits_cross_subchannel_interfaces(self):
        m=self.model();first=next(iter(m.selected_subchannels));rods=set(m.subchannels[first].rod_ids)
        second=next(i for i,s in m.subchannels.items() if s.sub_type=='interior' and i!=first and len(rods.intersection(s.rod_ids))==2)
        m.selected_subchannels.add(second)
        p=MeshParams(ni=8,nj=10,nz=2,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        layer=ms.build_mesh_from_bundle_model(m,p,allow_nonconformal=True)
        override={i:dict(core_mode='fixed_count',core_layers=5) for i in range(6,12)}
        full=ms.fill_subchannel_core(layer,m,core_mode='fixed_count',core_layers=3,allow_nonconformal=True,core_overrides=override)
        external=[i for i in full.diagnostics['interface_problems'] if i['block_a']//6!=i['block_b']//6]
        self.assertTrue(external);self.assertTrue(all(i['kind']=='nonconformal' for i in external))
    def test_geometry_mismatch_not_mistaken_for_nonconformal(self):
        m=self.model();p=MeshParams(ni=8,nj=10,nz=2)
        r=ms.build_mesh_from_bundle_model(m,p)
        x,y=r.blocks[0];blocks=list(r.blocks);blocks[0]=(x+1e-4,y)
        _,issues=partition_interfaces(blocks,r.interfaces,1e-12)
        self.assertTrue(any(i['kind']=='geometry_mismatch' for i in issues))
        broken=replace(r,diagnostics=dict(r.diagnostics,interface_problems=issues))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mesh.xyz';path.write_text('keep')
            with self.assertRaises(ValueError):ms.export_subchannel_plot3d(broken,path)
            self.assertEqual(path.read_text(),'keep')

if __name__=='__main__':unittest.main()
