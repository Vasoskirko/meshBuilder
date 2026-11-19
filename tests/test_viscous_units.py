import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_viscous_units import edge_ranges,wall_units,format_wall_units
from yplus_calculator import calculate_yplus_and_step
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow
from yplus_dialog import YPlusDialog

class ViscousUnitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_actual_edge_ranges_both_orientations_and_wall_scaling(self):
        x,y=np.meshgrid(np.arange(3)*.002,np.arange(4)*.001,indexing='ij')
        r=SimpleNamespace(blocks=[(x,y),(x[:,::-1],2*y[:,::-1])],wall_starts=[True,False],params=SimpleNamespace(nz=4,z_len=.02))
        ranges=edge_ranges(r)
        np.testing.assert_allclose(ranges['normal'],(.001,.002))
        np.testing.assert_allclose(ranges['first_normal'],(.001,.002))
        np.testing.assert_allclose(ranges['wall_azimuth'],(.002,.002))
        np.testing.assert_allclose(ranges['axial'],(.005,.005))
        ell,plus=wall_units(ranges,dict(nu=1e-6,u_tau=.1))
        self.assertAlmostEqual(ell,1e-5)
        np.testing.assert_allclose(plus['normal'],(100,200))
        np.testing.assert_allclose(plus['axial'],(500,500))
        text=format_wall_units(ranges,dict(nu=1e-6,u_tau=.1))
        self.assertIn('Δφ+',text);self.assertIn('Δz+',text);self.assertIn('Δn+',text)
        self.assertIn('y₁+',text)
        self.assertIn('min',text);self.assertIn('max',text)
        self.assertNotIn('Δs+',text)
        for bad in ({},dict(nu=0,u_tau=.1),dict(nu=1e-6,u_tau=float('nan'))):
            with self.assertRaises(ValueError):wall_units(ranges,bad)
        r.blocks=[]
        with self.assertRaises(ValueError):edge_ranges(r)
    def test_calculator_scale_and_first_center_are_consistent(self):
        r=calculate_yplus_and_step('velocity',2,1000,.001,10,50,y_plus=2)
        self.assertAlmostEqual(r['nu'],1e-6)
        self.assertAlmostEqual(r['viscous_length_m'],r['nu']/r['u_tau'])
        self.assertAlmostEqual(r['delta_y1_um']*1e-6/r['viscous_length_m'],4)
        self.assertAlmostEqual(r['y1_um']*1e-6/r['viscous_length_m'],2)
    def test_console_build_reference_update_and_stale_message(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        self.assertTrue(w.mesh_console.isReadOnly())
        self.assertTrue(w.mesh_subpanel.lbl_status.isHidden())
        self.assertEqual(w.mesh_console.maximumBlockCount(),600)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=5,nz=2)
        w.mesh_subpanel.apply_params(w.base_params)
        with patch.object(w,'redraw_mesh_views'),patch.object(w,'populate_blocks_table'),patch('bundle_subchannel_builder.QMessageBox.critical') as error:
            w.on_build_multiblock_mesh();error.assert_not_called()
        self.assertTrue(w.can_export_mesh())
        self.assertIn('Вязкие размеры недоступны',w.mesh_console.toPlainText())
        w.mesh_subpanel.last_yplus_result=dict(nu=1e-6,u_tau=.1)
        w.report_viscous_units()
        self.assertIn('Азимут Δφ+',w.mesh_console.toPlainText())
        result=w.current_mesh_result
        w.mesh_subpanel.last_yplus_result=dict(nu=2e-6,u_tau=.1)
        w.report_viscous_units()
        self.assertIs(w.current_mesh_result,result)
        self.assertTrue(w.can_export_mesh())
        self.assertIn('ℓν = 20 мкм',w.mesh_console.toPlainText())
        w.pitch_spin.setValue(w.pitch_spin.value()+.1)
        self.assertFalse(w.can_export_mesh())
        self.assertIn('Сетка устарела',w.mesh_console.toPlainText())
        w.report_viscous_units()
        self.assertIn('Нет актуальной сетки',w.mesh_console.toPlainText())
    def test_invalid_calculator_clears_previous_reference(self):
        dlg=YPlusDialog();self.addCleanup(dlg.deleteLater)
        self.assertIsNotNone(dlg.last_yplus_result)
        dlg.edit_temp.setText('invalid');dlg.recalc()
        self.assertIsNone(dlg.last_yplus_result)
        self.assertEqual(dlg.calculated_delta_y1_um,0)
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        w.mesh_subpanel.last_yplus_result=dict(nu=1e-6,u_tau=.1)
        with patch('mesh_subchannel_subpanel.YPlusDialog',return_value=dlg),patch.object(dlg,'exec',return_value=0):
            w.mesh_subpanel.open_yplus_calculator()
        self.assertEqual(w.mesh_subpanel.last_yplus_result,{})
