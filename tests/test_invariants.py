import dataclasses
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mesh_core import MeshParams, MeshState, check_mesh, generate_mesh, mesh_topology


class MeshInvariantTests(unittest.TestCase):
    def test_invalid_parameters(self):
        cases = [dict(d_rod=0), dict(pitch=0), dict(z_len=float('nan')),
                 dict(ni=True), dict(nj=2), dict(nz=0), dict(full=1),
                 dict(h1=0), dict(law='unknown'), dict(mode='unknown'),
                 dict(law='uniform', mode='first_count'),
                 dict(law='geometric', mode='shape_count'),
                 dict(mode='first_max', hmax=1e-9)]
        for values in cases:
            with self.subTest(**values):
                with self.assertRaises(ValueError):
                    generate_mesh(MeshParams(**values))

    def test_layer_validation(self):
        cases = [dict(wall_layers=1), dict(h1=0),
                 dict(layer_thickness=1e-6), dict(layer_thickness=0.01),
                 dict(mode='layer_first_growth', layer_growth=0.9)]
        for values in cases:
            with self.subTest(**values):
                params = dict(law='wall_core', mode='layer_thickness', ni=12)
                params.update(values)
                with self.assertRaises(ValueError):
                    generate_mesh(MeshParams(**params))

    def test_state_and_interfaces(self):
        for full in (False, True):
            for layer in (False, True):
                with self.subTest(full=full, layer=layer):
                    values = dict(ni=12, nj=40, nz=2, full=full)
                    if layer:
                        values.update(law='wall_core', mode='layer_thickness')
                    result = generate_mesh(MeshParams(**values))
                    self.assertEqual(result.complete, not layer)
                    self.assertEqual(result.state, MeshState.LAYER_ONLY if layer else MeshState.COMPLETE)
                    self.assertEqual(result.topology, mesh_topology(full, not layer))
                    minimum, count, error, turning = check_mesh(result)
                    self.assertGreater(minimum, 0)
                    self.assertEqual(count, len(result.topology.interfaces))
                    self.assertLessEqual(error, result.params.pitch * 1e-12)
                    self.assertTrue(np.isfinite(turning))
                    self.assertEqual(len(result.wall_start), len(result.blocks))
                    self.assertEqual(result.layer_widths.shape[0], result.params.ni)
                    self.assertTrue(np.all(np.isfinite(result.distances)))
                    self.assertTrue(np.all(np.diff(result.distances, axis=1) > 0))
                    with self.assertRaises(ValueError):
                        dataclasses.replace(result, topology=mesh_topology(full, layer))

    def test_rejects_degenerate_coordinates(self):
        result = generate_mesh(MeshParams(ni=12, nj=40, nz=2, full=False))
        blocks = [(x.copy(), y.copy()) for x, y in result.blocks]
        x, y = blocks[0]
        x[1, :] = x[0, :]
        y[1, :] = y[0, :]
        with self.assertRaises(ValueError):
            check_mesh(dataclasses.replace(result, blocks=blocks))


if __name__ == '__main__':
    unittest.main()
