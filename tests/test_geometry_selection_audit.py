"""Independent geometric invariants and hostile edit/selection sequences."""
import math,unittest
from copy import deepcopy
from unittest.mock import patch
import numpy as np
from bundle_geometry import BundleModel


def signature(model,sub):
    return (tuple(sorted((model.rods[r].q,model.rods[r].r) for r in sub.rod_ids)),sub.wall_side,sub.corner_index)

class GeometryAuditTests(unittest.TestCase):
    def test_reject_nonfinite_nonpositive_and_unbounded_work(self):
        for params in (dict(pitch=0),dict(pitch=-1),dict(s_flat=float('inf')),dict(d_fuel=float('nan')),dict(d_guide=-2),dict(pitch=9.1)):
            with self.subTest(params=params),self.assertRaises(ValueError):BundleModel(**params)
    def test_unbounded_lattice_rejected_before_allocating_points(self):
        with patch('bundle_geometry.np.array',side_effect=AssertionError('allocation attempted')):
            with self.assertRaises(ValueError):BundleModel(s_flat=1e9)
    def test_invalid_rebuild_does_not_erase_geometry(self):
        m=BundleModel();m.select_all_subchannels();old=deepcopy(m.rods);selected=set(m.selected_subchannels);m.pitch=0
        with self.assertRaises(ValueError):m.update_geometry()
        self.assertEqual(m.rods,old);self.assertEqual(m.selected_subchannels,selected)
    def test_selection_tracks_coordinates_not_recycled_ids(self):
        m=BundleModel();m.select_all_subchannels();old={signature(m,s) for s in m.subchannels.values()};m.active_sub_id=max(m.subchannels)
        m.active_rod_coord=(0,0);m.delete_active_rod_manually()
        self.assertTrue(m.selected_subchannels<=m.subchannels.keys())
        self.assertTrue({signature(m,m.subchannels[s]) for s in m.selected_subchannels}<=old)
        self.assertTrue(m.active_sub_id is None or m.active_sub_id in m.subchannels)
        m.get_candidate_neighbors();m.export_dict()
    def test_unaffected_selection_survives_rebuild(self):
        m=BundleModel();m.selected_subchannels={0,1};before={signature(m,m.subchannels[s]) for s in m.selected_subchannels};m.update_geometry()
        self.assertEqual(before,{signature(m,m.subchannels[s]) for s in m.selected_subchannels})
    def test_missing_selection_id_cannot_poison_export(self):
        m=BundleModel()
        for f in (m.add_subchannel,m.select_subchannel):
            with self.assertRaises(ValueError):f(10**9)
        self.assertFalse(m.selected_subchannels);self.assertIsNone(m.active_sub_id)
    def test_custom_fuel_diameter_and_reset_to_default(self):
        m=BundleModel();m.apply_rod_change((0,0),'fuel',10.)
        r=m.rods[m.coord_to_rod_id[(0,0)]];self.assertEqual(r.diameter,10.);self.assertTrue(r.custom_diameter)
        m.apply_rod_change((0,0),'fuel',None);self.assertEqual(m.rods[m.active_rod_id].diameter,m.d_fuel)
        m.apply_rod_change((0,0),'guide',10.);m.apply_rod_change((0,0),'guide',None)
        self.assertEqual(m.rods[m.active_rod_id].diameter,m.d_guide);self.assertFalse(m.rods[m.active_rod_id].custom_diameter)
    def test_bad_rod_edits_are_atomic(self):
        m=BundleModel();before=deepcopy(m.__dict__)
        for args in (((0,0),'invalid',10.),((0,0),'guide',float('nan')),((0,0),'fuel',-1.),((999,999),'guide',10.)):
            with self.subTest(args=args),self.assertRaises(ValueError):m.apply_rod_change(*args)
        self.assertEqual(m.user_rod_types,before['user_rod_types']);self.assertEqual(m.rods,before['rods'])
    def test_collinear_remaining_rods_do_not_crash_qhull(self):
        m=BundleModel();keep={(-1,0),(0,0),(1,0)}
        m.user_deleted_coords={c for c in m.coord_to_rod_id if c not in keep};m.update_geometry()
        self.assertEqual(len(m.rods),3);self.assertFalse(any(s.sub_type=='interior' for s in m.subchannels.values()))
    def test_full_section_conserves_area_and_wetted_perimeter(self):
        for size in (40.,65.,80.,100.):
            with self.subTest(size=size):
                m=BundleModel(s_flat=size)
                expected_area=math.sqrt(3)/2*size**2-sum(math.pi*r.diameter**2/4 for r in m.rods.values())
                expected_perimeter=2*math.sqrt(3)*size+sum(math.pi*r.diameter for r in m.rods.values())
                self.assertAlmostEqual(sum(s.a_poly_mm2 for s in m.subchannels.values()),math.sqrt(3)/2*size**2,delta=.001*len(m.subchannels))
                self.assertAlmostEqual(sum(s.a_fluid_mm2 for s in m.subchannels.values()),expected_area,delta=.001*len(m.subchannels))
                self.assertAlmostEqual(sum(s.p_wet_mm for s in m.subchannels.values()),expected_perimeter,delta=.001*len(m.subchannels))
    def test_graph_matches_independent_shared_edge_or_corner_rule(self):
        m=BundleModel();subs=m.subchannels
        for n,s in subs.items():
            self.assertEqual(len(s.neighbor_sub_ids),len(set(s.neighbor_sub_ids)));self.assertNotIn(n,s.neighbor_sub_ids)
            for other in s.neighbor_sub_ids:self.assertIn(n,subs[other].neighbor_sub_ids)
            expected={k for k,t in subs.items() if k!=n and (set(s.boundary_edges)&set(t.boundary_edges) or s.corner_index>=0 and s.corner_index==t.corner_index)}
            self.assertEqual(set(s.neighbor_sub_ids),expected)
    def test_overlapping_special_tubes_are_marked_and_not_used(self):
        m=BundleModel();m.apply_rod_change((0,0),'guide',14.)
        m.apply_rod_change((1,0),'instrument',14.)
        pair={m.coord_to_rod_id[c] for c in ((0,0),(1,0))}
        self.assertTrue(all(m.rods[r].is_clashing for r in pair))
        self.assertTrue(any(set(c.get('rod_ids',()))==pair for c in m.detected_clashes))
        self.assertFalse(any(pair & set(s.rod_ids) for s in m.subchannels.values()))
    def test_wall_intersection_rejected_without_deleting_rod(self):
        m=BundleModel();r=max(m.rods.values(),key=lambda r:r.x);before=deepcopy(m.rods)
        with self.assertRaisesRegex(ValueError,'оболочку'):m.apply_rod_change((r.q,r.r),'guide',60.)
        self.assertEqual(m.rods,before)
    def test_unequal_wall_rods_conserve_total_area(self):
        m=BundleModel();r=max(m.rods.values(),key=lambda r:r.x);m.apply_rod_change((r.q,r.r),'guide',10.)
        expected=math.sqrt(3)/2*m.s_flat**2-sum(math.pi*r.diameter**2/4 for r in m.rods.values())
        self.assertAlmostEqual(sum(s.a_fluid_mm2 for s in m.subchannels.values()),expected,delta=.04)
    def test_seeded_selection_delete_restore_edit_sequence(self):
        import random
        rng=random.Random(20261127);m=BundleModel()
        for _ in range(60):
            op=rng.randrange(5)
            if op==0 and m.subchannels:m.select_subchannel(rng.choice(list(m.subchannels)))
            elif op==1 and m.rods:
                r=rng.choice(list(m.rods.values()));m.active_rod_coord=(r.q,r.r);m.delete_active_rod_manually()
            elif op==2:m.restore_deleted_rods()
            elif op==3 and m.rods:
                r=rng.choice(list(m.rods.values()));m.apply_rod_change((r.q,r.r),'fuel',9.5)
            else:m.clear_all_selection()
            self.assertTrue(m.selected_subchannels<=m.subchannels.keys());m.export_dict();m.get_candidate_neighbors()
            for sub in m.subchannels.values():
                self.assertTrue(set(sub.rod_ids)<=m.rods.keys())
                self.assertTrue(all(math.isfinite(v) for v in (sub.a_fluid_mm2,sub.p_wet_mm,sub.d_h_mm)))
