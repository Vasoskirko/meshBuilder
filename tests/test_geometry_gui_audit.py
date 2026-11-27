"""Exercise geometry editing slots, including cancellation and failed rebuilds."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow

class GeometryGuiAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        w=BundleBuilderWindow();self.addCleanup(w.close);self.addCleanup(w.deleteLater);return w
    def test_bad_rebuild_preserves_original_geometry_overrides_and_selection(self):
        w=self.window();w.model.apply_rod_change((0,0),'guide',10.);w.model.select_all_subchannels();before=w.model.export_dict();original=w.model
        w.pitch_spin.setValue(5.)
        with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:w.on_rebuild_geometry()
        warning.assert_called_once();self.assertIs(w.model,original);self.assertEqual(w.model.export_dict(),before)
    def test_custom_fuel_edit_is_applied_through_inspector(self):
        w=self.window();w.model.active_rod_coord=(0,0);w.update_inspector();w.rod_diam_spin.setValue(10.)
        w.apply_custom_rod_diameter();self.assertEqual(w.model.rods[w.model.active_rod_id].diameter,10.)
    def test_dismiss_collision_prompt_cancels_change_and_restores_controls(self):
        w=self.window();w.model.active_rod_coord=(0,0);w.update_inspector();rid=w.model.active_rod_id;old=w.model.rods[rid].diameter
        w.d_guide_spin.setValue(20.)
        with patch('bundle_subchannel_builder.QMessageBox') as box:
            box.return_value.clickedButton.return_value=None
            w.rod_type_combo.setCurrentIndex(w.rod_type_combo.findData('guide'))
        self.assertEqual(w.model.rods[rid].rod_type,'fuel');self.assertEqual(w.rod_diam_spin.value(),old)
        self.assertEqual(w.rod_type_combo.currentData(),'fuel');self.assertFalse(w.model.auto_deleted_clash_coords)
    def test_delete_selected_rod_then_neighbors_and_export(self):
        w=self.window();w.on_select_all_subchannels();w.model.active_rod_coord=(0,0);w.on_delete_rod_manually()
        w.model.export_dict();w.model.get_candidate_neighbors();w.on_restore_deleted_rods();w.on_clear_selection()
        self.assertFalse(w.model.selected_subchannels);self.assertIsNone(w.model.active_rod_coord)
    def test_click_outside_shell_does_not_select_nearby_channel(self):
        w=self.window();w.model.clear_all_selection();w.model.active_rod_coord=(0,0)
        sub=next(s for s in w.model.subchannels.values() if s.sub_type=='corner')
        normal=w.model.normals[sub.wall_side];x,y=sub.fluid_center
        distance=w.model.s_flat/2-x*normal[0]-y*normal[1]+.1
        w.handle_unified_click(x+distance*normal[0],y+distance*normal[1])
        self.assertFalse(w.model.selected_subchannels);self.assertIsNone(w.model.active_rod_coord)
