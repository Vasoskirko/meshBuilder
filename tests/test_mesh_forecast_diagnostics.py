import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest,tempfile
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_core_fill import controlled_distribution
from mesh_subchannel import build_mesh_from_bundle_model,fill_subchannel_core,export_subchannel_plot3d
from mesh_quality import cell_metrics,extrude_blocks
from bundle_mesh_preview import forecast
from mesh_visual_diagnostics import diagnose
from bundle_subchannel_builder import BundleBuilderWindow

CORE=dict(mode='controlled_growth',growth=1.2,size=.0002,limit=5000,layers=15,transition=1.1)

class MeshForecastDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def model(self):
        m=BundleModel();m.selected_subchannels={next(i for i,s in m.subchannels.items() if s.sub_type=='interior')};return m
    def test_fixed_forecast_matches_actual_mesh_and_ascii_size(self):
        m=self.model();p=MeshParams(ni=8,nj=10,nz=3)
        data=forecast(m,p,{}, {},CORE)
        result=build_mesh_from_bundle_model(m,p)
        count=sum((x.shape[0]-1)*(x.shape[1]-1)*p.nz for x,y in result.blocks)
        self.assertTrue(data['exact']);self.assertEqual(data['full']['cells'],(count,count))
        arrays=extrude_blocks(result.blocks,np.linspace(0,p.z_len,p.nz+1))
        self.assertEqual(data['full']['coordinates_3d'],(sum(a.nbytes for a in arrays),)*2)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mesh.xyz';export_subchannel_plot3d(result,path)
            self.assertLessEqual(data['full']['xyz_bytes'][0],path.stat().st_size)
            self.assertGreaterEqual(data['full']['xyz_bytes'][1],path.stat().st_size)
    def test_auto_range_and_refined_strict_and_aspect_forecasts(self):
        m=self.model();p=MeshParams(ni=8,nj=10,nz=2,mode='first_growth',shape=1.2)
        data=forecast(m,p,{}, {},CORE);result=build_mesh_from_bundle_model(m,p)
        self.assertFalse(data['exact']);self.assertLessEqual(data['full']['cells'][0],result.diagnostics['cells_3d']);self.assertGreaterEqual(data['full']['cells'][1],result.diagnostics['cells_3d'])
        p=replace(p,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        layer=build_mesh_from_bundle_model(m,p)
        broad=forecast(m,p,{}, {},CORE);self.assertFalse(broad['exact'])
        for mode in ('controlled_growth','aspect_alignment','fixed_count'):
            core=dict(CORE,mode=mode)
            preview=forecast(m,p,{}, {},core,layer)
            full=fill_subchannel_core(layer,m,core_mode=mode,growth=core['growth'],max_size=core['size'],transition_ratio=core['transition'],core_layers=core['layers'])
            count=full.diagnostics['cells_3d']
            self.assertLessEqual(preview['full']['cells'][0],count);self.assertGreaterEqual(preview['full']['cells'][1],count)
            self.assertEqual(preview['exact'],mode!='aspect_alignment')
            self.assertEqual(preview['layer']['cells'],(layer.diagnostics['cells_3d'],)*2)
    def test_count_only_does_not_allocate_distribution_matrix(self):
        lengths=np.array([.0008,.001]);last=np.array([5e-6,5e-6])
        actual=controlled_distribution(lengths,last,1.2,.0001,1000,1.1)
        with patch('mesh_core_fill.np.empty',side_effect=AssertionError('matrix allocated')):
            lo,hi=controlled_distribution(lengths,last,1.2,.0001,1000,1.1,count_only=True)
        self.assertEqual(lo,actual.count);self.assertGreaterEqual(hi,lo)
        self.assertEqual(controlled_distribution(np.array([1.,1.]),.1,1,.1,100,count_only=True),(10,10))
    def grid(self,ys=None):
        x,y=np.meshgrid(np.linspace(0,1,5),np.array(ys) if ys is not None else np.linspace(0,2,6),indexing='ij')
        return SimpleNamespace(params=SimpleNamespace(z_len=.03,nz=3),blocks=[(x,y)],wall_starts=[True],instances_map=[])
    def test_chunked_diagnostics_match_full_metrics_and_limit_display(self):
        result=self.grid();x,y=result.blocks[0];x[2,2]+=.08
        full=cell_metrics(extrude_blocks(result.blocks,np.linspace(0,.03,4))[0])
        data=diagnose(result,'jacobian',.999,limit=100,chunk_cells=4)
        expected=full['scaled_jacobian'][:,:,0]<.999
        self.assertEqual(data['bad'],int(expected.sum()))
        for row in data['records']:
            self.assertAlmostEqual(row['metrics']['jacobian'],full['scaled_jacobian'][row['i'],row['j'],0])
        fine=diagnose(result,'aspect',1.01,limit=3,chunk_cells=4)
        broad=diagnose(result,'aspect',1.01,limit=100,chunk_cells=10000)
        self.assertEqual(fine['bad'],broad['bad']);self.assertLessEqual(len(fine['records']),3)
        self.assertAlmostEqual(fine['maximum'],broad['maximum'])
    def test_transition_detects_both_neighbors_and_invalid_cells(self):
        result=self.grid([0,.1,.2,.7])
        data=diagnose(result,'transition',2,limit=100,chunk_cells=3)
        self.assertEqual(data['bad'],8)
        self.assertEqual({r['j'] for r in data['records']},{1,2})
        result.blocks=[tuple(a[::-1] for a in result.blocks[0])]
        invalid=diagnose(result,'jacobian',0)
        self.assertEqual(invalid['invalid'],invalid['total']);self.assertEqual(invalid['bad'],invalid['total'])
        with self.assertRaises(ValueError):diagnose(result,'aspect',0)
    def test_gui_forecast_overlay_inspection_and_invalidation(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=2);w.mesh_subpanel.apply_params(w.base_params)
        with patch('bundle_subchannel_builder.QMessageBox.critical') as error,patch('bundle_diagnostics_ui.QMessageBox.warning') as warning:
            w.on_build_multiblock_mesh();result=w.current_mesh_result;self.assertTrue(w.can_export_mesh())
            w.on_estimate_mesh();self.assertIn('ПРОГНОЗ СЕТКИ',w.mesh_console.toPlainText())
            self.assertIs(w.current_mesh_result,result);self.assertTrue(w.can_export_mesh())
            w.combo_mesh_diagnostic.setCurrentIndex(w.combo_mesh_diagnostic.findData('aspect'))
            w.spin_diagnostic_threshold.setValue(1.0);w.on_mesh_diagnostic()
            error.assert_not_called();warning.assert_not_called()
        self.assertTrue(w._mesh_diagnostic['records']);self.assertTrue(w.can_export_mesh())
        self.assertTrue(any(a.get_gid()=='mesh-diagnostic' for a in w.ax_mesh.collections))
        row=w._mesh_diagnostic['records'][0];xy=np.mean(row['corners'],axis=0)*1e3
        event=SimpleNamespace(inaxes=w.ax_mesh,button=1,xdata=xy[0],ydata=xy[1])
        w.on_diagnostic_click(event)
        self.assertIs(w._selected_diagnostic,row);self.assertIn('ЯЧЕЙКА:',w.mesh_console.toPlainText())
        w.chk_mesh_diagnostic.setChecked(False);self.assertTrue(w.can_export_mesh())
        w.mesh_subpanel.fields['ni'].setValue(9)
        self.assertFalse(w.can_export_mesh());self.assertIsNone(w._mesh_diagnostic)
        self.assertFalse(any(a.get_gid()=='mesh-diagnostic' for a in w.ax_mesh.collections))

    def test_variant_a_comparison_and_origin_explanations(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=2);p=w.mesh_subpanel;p.apply_params(w.base_params)
        with patch('bundle_subchannel_builder.QMessageBox.critical') as error:
            w.on_build_multiblock_mesh();a=w.current_mesh_result
            w.remember_mesh_variant();self.assertIs(w._mesh_variant_a['mesh'],a)
            p.fields['layers'].setValue(12);self.assertFalse(w.can_export_mesh())
            self.assertIsNotNone(w._mesh_variant_a)
            w.on_build_multiblock_mesh();self.assertTrue(w.can_export_mesh())
            self.assertIsNot(w.current_mesh_result,a)
            self.assertTrue(any(artist.get_gid()=='mesh-variant-a' for artist in w.ax_mesh.collections))
            w.compare_mesh_variant();self.assertIn('СРАВНЕНИЕ СЕТОК',w.mesh_console.toPlainText())
            current=w.current_mesh_result;w.clear_mesh_variant()
            self.assertIsNone(w._mesh_variant_a);self.assertIs(w.current_mesh_result,current)
            self.assertFalse(any(artist.get_gid()=='mesh-variant-a' for artist in w.ax_mesh.collections))
            error.assert_not_called()
        p.radio_template.setChecked(True)
        self.assertFalse(p.fields['ni'].isEnabled());self.assertIn('наследует общие',p.lbl_parameter_origin.text())
        p.fields['h1'].setValue(p.fields['h1'].value()*1.01);p.fields['h1'].edited.emit()
        self.assertIn('собственные',p.lbl_parameter_origin.text())
        p.radio_block.setChecked(True);self.assertIn('шаблон T',p.lbl_parameter_origin.text())
        p.fields['h1'].setValue(p.fields['h1'].value()*1.01);p.fields['h1'].edited.emit()
        self.assertIn('собственное переопределение',p.lbl_parameter_origin.text())
        p.radio_all.setChecked(True);self.assertTrue(p.fields['ni'].isEnabled())
    def test_pending_wall_draft_blocks_core_and_fixed_mode_ignores_hidden_fields(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=10,nz=1,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        p=w.mesh_subpanel;p.apply_params(w.base_params)
        with patch('bundle_subchannel_builder.QMessageBox.critical') as error,patch('bundle_subchannel_builder.QMessageBox.information'):
            w.on_build_layer_only()
            p.fields['h1'].setText('6')
            with patch('bundle_subchannel_builder.ms.fill_subchannel_core') as fill:
                w.on_fill_core_clicked();fill.assert_not_called()
            self.assertIsNone(w.current_layer_result);self.assertFalse(w.can_export_mesh())
            self.assertTrue(error.called);error.reset_mock()
            w.on_build_layer_only()
            p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'))
            p.fields['core_max_size'].setText('invalid')
            p.fields['core_layers'].lineEdit().setText('15')
            w.on_estimate_mesh();w.on_fill_core_clicked()
            error.assert_not_called();self.assertTrue(w.can_export_mesh())
            self.assertEqual(w.current_mesh_result.diagnostics['core_layers_count'],15)
