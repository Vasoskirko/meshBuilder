"""State-machine tests; result fixtures do not represent generated meshes."""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mesh_layer import layer_distribution
from mesh_params import MeshParams
from mesh_workflow import MeshWorkflow


class WorkflowInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.params = MeshParams(law='wall_core', mode='layer_first_growth',
                                 ni=12, nz=2, full=False, h1=5e-6,
                                 wall_layers=4, layer_growth=1.1,
                                 layer_thickness=100e-6)
        self.layer = self.result_fixture(self.params, complete=False)
        self.core = self.result_fixture(self.params, complete=True)
        self.workflow = MeshWorkflow()

    @staticmethod
    def result_fixture(params, complete):
        return SimpleNamespace(params=params, requested=params, complete=complete)

    def accept_complete(self):
        self.workflow.accept_mesh(self.layer)
        self.workflow.accept_core(self.core)

    def test_empty_workflow_disallows_fill_and_export(self):
        self.assertFalse(self.workflow.can_fill)
        self.assertFalse(self.workflow.can_export)

    def test_layer_is_reusable_but_not_exportable(self):
        self.workflow.accept_mesh(self.layer)
        self.assertTrue(self.workflow.can_fill)
        self.assertFalse(self.workflow.can_export)
        self.assertIs(self.workflow.layer, self.layer)

    def test_core_invalidation_preserves_layer_identity(self):
        self.accept_complete()
        self.assertTrue(self.workflow.can_export)
        self.workflow.invalidate_core()
        self.assertIs(self.workflow.layer, self.layer)
        self.assertIs(self.workflow.result, self.layer)
        self.assertTrue(self.workflow.can_fill)
        self.assertFalse(self.workflow.can_export)
        self.workflow.accept_core(self.core)
        self.assertTrue(self.workflow.can_export)

    def test_layer_invalidation_blocks_fill_export_and_core_acceptance(self):
        self.accept_complete()
        self.workflow.invalidate_layer()
        self.workflow.invalidate_core()
        self.assertFalse(self.workflow.can_fill)
        self.assertFalse(self.workflow.can_export)
        self.assertFalse(self.workflow.matches_layer(self.params))
        with self.assertRaises(ValueError):
            self.workflow.accept_core(self.core)

    def test_geometry_changes_do_not_match_saved_layer(self):
        self.workflow.accept_mesh(self.layer)
        for values in ({'z_len': 0.1}, {'ni': 14}, {'nz': 3},
                       {'pitch': 0.013}, {'d_rod': 0.009}, {'full': True}):
            with self.subTest(**values):
                self.assertFalse(self.workflow.matches_layer(replace(self.params, **values)))

    def test_first_growth_h1_change_changes_distribution_and_rejects_core(self):
        self.workflow.accept_mesh(self.layer)
        changed = replace(self.params, h1=self.params.h1 * 2)
        original_widths, _ = layer_distribution(self.params)
        changed_widths, _ = layer_distribution(changed)
        np.testing.assert_allclose(changed_widths, original_widths * 2)
        self.assertFalse(self.workflow.matches_layer(changed))
        with self.assertRaises(ValueError):
            self.workflow.accept_core(self.result_fixture(changed, complete=True))
        self.assertIs(self.workflow.result, self.layer)

    def test_first_growth_ignores_inactive_thickness(self):
        self.workflow.accept_mesh(self.layer)
        changed = replace(self.params, layer_thickness=200e-6)
        original_widths, _ = layer_distribution(self.params)
        changed_widths, _ = layer_distribution(changed)
        np.testing.assert_array_equal(changed_widths, original_widths)
        self.assertTrue(self.workflow.matches_layer(changed))

    def test_active_parameters_are_checked_for_each_layer_mode(self):
        cases = {
            'layer_first_growth': ({'h1': 6e-6}, {'wall_layers': 5}, {'layer_growth': 1.2}),
            'layer_thickness': ({'h1': 6e-6}, {'wall_layers': 5}, {'layer_thickness': 200e-6}),
            'layer_growth': ({'layer_growth': 1.2}, {'wall_layers': 5}, {'layer_thickness': 200e-6}),
        }
        for mode, changes in cases.items():
            params = replace(self.params, mode=mode)
            self.workflow.accept_mesh(self.result_fixture(params, complete=False))
            self.assertTrue(self.workflow.matches_layer(params))
            for values in changes:
                with self.subTest(mode=mode, values=values):
                    self.assertFalse(self.workflow.matches_layer(replace(params, **values)))

    def test_other_modes_ignore_inactive_wall_parameter(self):
        for mode, values in (('layer_thickness', {'layer_growth': 1.2}),
                             ('layer_growth', {'h1': 6e-6})):
            with self.subTest(mode=mode):
                params = replace(self.params, mode=mode)
                self.workflow.accept_mesh(self.result_fixture(params, complete=False))
                self.assertTrue(self.workflow.matches_layer(replace(params, **values)))

    def test_rebuilt_layer_restores_fill_but_not_export(self):
        self.accept_complete()
        self.workflow.invalidate_layer()
        params = replace(self.params, h1=6e-6)
        rebuilt = self.result_fixture(params, complete=False)
        self.workflow.accept_mesh(rebuilt)
        self.assertIs(self.workflow.layer, rebuilt)
        self.assertTrue(self.workflow.can_fill)
        self.assertFalse(self.workflow.can_export)
        self.assertTrue(self.workflow.matches_layer(params))
        self.assertFalse(self.workflow.matches_layer(self.params))


if __name__ == '__main__':
    unittest.main()
