"""Exercise the bundle GUI build/edit/export lifecycle without a display."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_API'] = 'pyside6'

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow


class BundleMeshInvalidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = BundleBuilderWindow()
        self.addCleanup(self.w.deleteLater)
        self.p = self.w.mesh_subpanel
        sid = next(sid for sid, s in self.w.model.subchannels.items()
                   if s.sub_type == 'interior')
        self.w.model.selected_subchannels = {sid}
        self.w.switch_to_mesh_mode()
        for name in ('redraw_mesh_views', 'populate_blocks_table'):
            mock = patch.object(self.w, name)
            mock.start()
            self.addCleanup(mock.stop)
        for name in ('information', 'warning', 'critical'):
            mock = patch('bundle_subchannel_builder.QMessageBox.' + name)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)
        self.w.base_params = replace(self.w.base_params, ni=8, nj=5, nz=1)
        self.p.apply_params(self.w.base_params)

    def build(self, wall=False):
        if wall:
            self.w.base_params = replace(self.w.base_params, law='wall_core',
                mode='layer_first_growth', wall_layers=4, h1=5e-6, layer_growth=1.1)
            self.p.apply_params(self.w.base_params)
        if self.w.base_params.law=='wall_core':self.w.on_build_layer_only()
        else:self.w.on_build_multiblock_mesh()
        self.critical.assert_not_called()
        self.assertIsNotNone(self.w.current_mesh_result)

    def exports(self, allowed):
        with patch('bundle_subchannel_builder.QFileDialog.getSaveFileName', return_value=('test.xyz', '')) as chooser, patch('bundle_subchannel_builder.ms.export_subchannel_plot3d') as writer, patch('starccm_export_dialog.StarCcmExportDialog') as star:
            self.w.on_export_plot3d()
            self.w.on_export_starccm_dialog()
            self.assertEqual(writer.call_count, int(allowed))
            self.assertEqual(chooser.call_count, int(allowed))
            self.assertEqual(star.call_count, int(allowed))
        self.assertEqual(self.p.btn_export.isEnabled(), allowed)
        self.assertEqual(self.p.btn_export_star.isEnabled(), allowed)

    def test_build_edit_export_blocked_rebuild_export_allowed(self):
        self.build()
        self.exports(True)
        self.p.fields['ni'].setValue(10)
        self.assertIsNone(self.w.current_quality_report)
        self.exports(False)
        self.build()
        self.exports(True)

    def test_delete_restore_rods_never_revives_old_mesh_or_layer(self):
        self.build(wall=True)
        self.p.combo_core_mode.setCurrentIndex(self.p.combo_core_mode.findData('fixed_count'))
        self.p.fields['core_layers'].setValue(3)
        self.w.on_fill_core_clicked()
        self.exports(True)
        self.w.model.active_rod_coord=(0,0)
        self.w.on_delete_rod_manually()
        self.exports(False)
        self.assertIsNone(self.w.current_layer_result)
        self.w.on_restore_deleted_rods()
        self.exports(False)
        self.assertIsNone(self.w.current_layer_result)
        sid=next(k for k,s in self.w.model.subchannels.items() if s.sub_type=='interior')
        self.w.model.selected_subchannels={sid}
        self.w.switch_to_mesh_mode()
        self.build()
        self.w.on_fill_core_clicked()
        self.exports(True)

    def test_core_edit_preserves_layer_and_refill_restores_exports(self):
        self.build(wall=True)
        layer = self.w.current_layer_result
        self.exports(False)
        self.p.combo_core_mode.setCurrentIndex(self.p.combo_core_mode.findData('fixed_count'))
        self.p.fields['core_layers'].setValue(3)
        self.w.on_fill_core_clicked()
        self.critical.assert_not_called()
        self.exports(True)
        self.p.fields['core_layers'].setValue(4)
        self.assertIs(self.w.current_layer_result, layer)
        self.assertTrue(self.p.btn_fill_core.isEnabled())
        self.exports(False)
        self.w.on_fill_core_clicked()
        self.critical.assert_not_called()
        self.exports(True)

    def test_wall_edit_blocks_direct_fill_and_rebuild_replaces_layer(self):
        self.build(wall=True)
        old = self.w.current_layer_result
        self.p.fields['layer_cells'].setValue(5)
        self.assertIsNone(self.w.current_layer_result)
        with patch('bundle_subchannel_builder.ms.fill_subchannel_core') as fill:
            self.w.on_fill_core_clicked()
            fill.assert_not_called()
        self.exports(False)
        self.build()
        self.assertIsNot(self.w.current_layer_result, old)

    def test_scope_navigation_preserves_mesh_and_wall_fields(self):
        self.build(wall=True)
        result = self.w.current_mesh_result
        for radio in (self.p.radio_template, self.p.radio_block, self.p.radio_all):
            radio.setChecked(True)
            self.w.validate_mesh_inputs()
            self.assertIs(self.w.current_mesh_result, result)
            self.assertEqual(self.p.fields['layer_cells'].value(), 4)

    def test_geometry_selection_and_override_changes_block_exports(self):
        for edit in (
            lambda: self.w.pitch_spin.setValue(13),
            self.w.on_clear_selection,
            lambda: self.p.combo_center_method.setCurrentIndex(1),
            lambda: self.p.combo_mesh_lines.setCurrentIndex(0),
            lambda: self.w.template_configs.update({1: replace(self.w.base_params, ni=12)}),
            lambda: self.w.block_custom_configs.update({1: replace(self.w.base_params, ni=12)}),
        ):
            with self.subTest(edit=edit):
                self.build()
                edit()
                self.exports(False)
                # Restore selection for the next real build.
                sid = next(sid for sid, s in self.w.model.subchannels.items() if s.sub_type == 'interior')
                self.w.model.selected_subchannels = {sid}
                self.w.template_configs.clear()
                self.w.block_custom_configs.clear()

    def test_reset_override_invalidates_but_empty_reset_does_not(self):
        self.p.radio_template.setChecked(True)
        tid = self.p.combo_templates.currentData()
        self.w.template_configs[tid] = replace(self.w.base_params, filename="override.xyz")
        self.p.load_active_scope_to_ui()
        self.build()
        self.p.on_reset_override()
        self.exports(False)
        self.p.radio_all.setChecked(True)
        self.build()
        self.p.radio_template.setChecked(True)
        result = self.w.current_mesh_result
        self.p.on_reset_override()
        self.assertIs(self.w.current_mesh_result, result)

    def test_core_controls_in_override_scope_keep_layer_and_create_local_override(self):
        self.build(wall=True)
        layer = self.w.current_layer_result
        for radio in (self.p.radio_template, self.p.radio_block):
            radio.setChecked(True)
            self.p.fields['core_layers'].setValue(self.p.fields['core_layers'].value() + 1)
            field = self.p.fields['core_growth']
            field.setText('1.2')
            field.edited.emit()
            self.assertIs(self.w.current_layer_result, layer)
            self.assertTrue(self.w.template_configs)
        self.assertTrue(self.w.block_custom_configs)

    def test_numeric_wall_edit_signal_invalidates_layer(self):
        self.build(wall=True)
        field = self.p.fields['h1']
        field.setText('6')
        field.edited.emit()
        self.assertIsNone(self.w.current_layer_result)
        self.assertFalse(self.p.btn_fill_core.isEnabled())

    def test_rod_edit_and_selection_only_navigation(self):
        self.build(wall=True)
        layer = self.w.current_layer_result
        rod = next(iter(self.w.model.rods.values()))
        self.w.model.active_rod_coord = (rod.q, rod.r)
        self.w.on_deselect_rod()
        self.assertIs(self.w.current_layer_result, layer)
        rod.diameter += 0.1
        with patch('bundle_subchannel_builder.ms.fill_subchannel_core') as fill:
            self.w.on_fill_core_clicked()
            fill.assert_not_called()
        self.assertIsNone(self.w.current_layer_result)
