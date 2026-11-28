"""A selected wall region must never disappear silently from a CFD mesh."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from meshbuilder.geometry.mesh_support import require_supported_mesh


class MeshSupportTests(unittest.TestCase):
    def test_every_wall_region_and_mixed_selection_rejected_before_build(self):
        m=BundleModel(s_flat=80)
        regular=next(k for k,s in m.subchannels.items() if s.sub_type=='interior')
        walls=[k for k,s in m.subchannels.items() if s.sub_type in ('peripheral','corner')]
        self.assertTrue(walls)
        self.assertEqual({m.subchannels[k].sub_type for k in walls},{'peripheral','corner'})
        for sid in walls:
            for selection in ([sid],[regular,sid]):
                with self.subTest(selection=selection),patch('mesh_subchannel.classify_subchannel_blocks') as classify:
                    with self.assertRaisesRegex(ValueError,'S'+str(sid)):
                        build_mesh_from_bundle_model(m,MeshParams(),selected_sub_ids=selection)
                    classify.assert_not_called()

    def test_stale_id_rejected_and_regular_mesh_unchanged(self):
        m=BundleModel()
        with self.assertRaisesRegex(ValueError,'отсутствует'):require_supported_mesh(m,[99999])
        sid=next(k for k,s in m.subchannels.items() if s.sub_type=='interior')
        result=build_mesh_from_bundle_model(m,MeshParams(ni=8,nj=5,nz=1),selected_sub_ids=[sid])
        self.assertTrue(result.complete)
        self.assertEqual(result.diagnostics['skipped_peripheral'],0)

    def test_gui_select_all_explains_limit_without_switching_editor(self):
        from PySide6.QtWidgets import QApplication
        from bundle_subchannel_builder import BundleBuilderWindow
        app=QApplication.instance() or QApplication([])
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        w.on_select_all_subchannels()
        before=w.left_stack.currentIndex()
        with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:
            w.switch_to_mesh_mode()
        warning.assert_called_once()
        self.assertIn('Частичная CFD-сетка не создаётся',warning.call_args.args[2])
        self.assertEqual(w.left_stack.currentIndex(),before)
