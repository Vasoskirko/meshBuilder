"""Spatial broad phase must never omit a match accepted by the old scan."""
import unittest
from unittest.mock import patch
import numpy as np
from bundle_geometry import BundleModel
from mesh_core import MeshParams
import mesh_subchannel as ms


class InterfaceSearchTests(unittest.TestCase):
    def exhaustive(self, faces, tol):
        return ((i, j) for i in range(len(faces)) for j in range(i+1, len(faces)))

    def test_candidates_include_tolerance_edges_reversed_and_different_counts(self):
        rng = np.random.default_rng(41)
        faces = []
        tol = 1e-6
        for k in range(30):
            a = rng.normal(size=(7, 2))
            for v in (a, a[::-1], a+tol*.99, a[[0, 3, -1]]):
                faces.append((len(faces), 'i_min', v))
        # Exactly on the tolerance boundary, including zero coordinates.
        faces.extend([(200, 'i_min', np.array([[0., 0.], [1., 1.]])),
                      (201, 'i_min', np.array([[tol, -tol], [1., 1.]]))])
        candidates = list(ms._candidate_face_pairs(faces, tol))
        self.assertEqual(candidates, sorted(set(candidates)))
        candidates = set(candidates)
        for i, j in self.exhaustive(faces, tol):
            a, b = faces[i][2], faces[j][2]
            matches = any(np.allclose(a[[0, -1]], b[idx], rtol=0, atol=tol)
                          for idx in ([0, -1], [-1, 0]))
            if matches:
                self.assertIn((i, j), candidates)

    def test_build_matches_exhaustive_topology_and_coordinates(self):
        m = BundleModel()
        m.selected_subchannels = {i for i, s in m.subchannels.items() if s.sub_type=='interior'}
        p = MeshParams(ni=8, nj=10, nz=3)
        fast = ms.build_mesh_from_bundle_model(m, p)
        with patch.object(ms, '_candidate_face_pairs', self.exhaustive):
            reference = ms.build_mesh_from_bundle_model(m, p)
        self.assertEqual(fast.interfaces, reference.interfaces)
        self.assertEqual(fast.diagnostics, reference.diagnostics)
        for a, b in zip(fast.blocks, reference.blocks):
            for x, y in zip(a, b):
                np.testing.assert_array_equal(x, y)

    def test_build_progress_can_cancel_between_subchannels(self):
        m = BundleModel()
        m.selected_subchannels = {i for i, s in m.subchannels.items() if s.sub_type=='interior'}
        seen = []
        def cancel(fraction, text):
            seen.append(fraction)
            if fraction > 0:
                raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            ms.build_mesh_from_bundle_model(m, MeshParams(ni=8, nj=10), progress_callback=cancel)
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
