import unittest
import numpy as np
from bundle_geometry import BundleModel
from meshbuilder.geometry.peripheral_mesh import build_peripheral_preview


class PeripheralTopologyTests(unittest.TestCase):
    def test_all_six_walls_positive_cells_and_convergent_area(self):
        m=BundleModel(s_flat=80)
        channels=[s for s in m.subchannels.values() if s.sub_type=='peripheral']
        self.assertEqual({s.wall_side for s in channels},set(range(6)))
        for sub in channels:
            errors=[]
            for count in (17,65):
                blocks=build_peripheral_preview(m,sub.sub_id,count,13)
                self.assertEqual(len(blocks),4)
                area=0
                for x,y in blocks:
                    pts=np.stack([np.stack((x[:-1,:-1],y[:-1,:-1]),-1),np.stack((x[1:,:-1],y[1:,:-1]),-1),np.stack((x[1:,1:],y[1:,1:]),-1),np.stack((x[:-1,1:],y[:-1,1:]),-1)],-2)
                    cross=pts[...,0]*np.roll(pts[...,1],-1,axis=-1)-pts[...,1]*np.roll(pts[...,0],-1,axis=-1)
                    cells=cross.sum(-1)/2
                    self.assertTrue(np.all(cells>0));area+=cells.sum()
                errors.append(abs(area*1e6-sub.a_fluid_mm2))
            self.assertLess(errors[1],errors[0]/10)
            self.assertLess(errors[1]/sub.a_fluid_mm2,1e-4)

    def test_invalid_topology_and_allocation_rejected(self):
        m=BundleModel(s_flat=80)
        interior=next(k for k,s in m.subchannels.items() if s.sub_type=='interior')
        with self.assertRaises(ValueError):build_peripheral_preview(m,interior)
        sid=next(k for k,s in m.subchannels.items() if s.sub_type=='peripheral')
        for count in (True,2,514,3.5):
            with self.assertRaises(ValueError):build_peripheral_preview(m,sid,count)

    def test_shared_edges_match_and_unequal_radii_remain_valid(self):
        m=BundleModel(s_flat=80)
        sub=next(s for s in m.subchannels.values() if s.sub_type=='peripheral')
        m.rods[sub.rod_ids[0]].diameter=10.3
        blocks=build_peripheral_preview(m,sub.sub_id,25,25)
        edges=[]
        for bid,(x,y) in enumerate(blocks):
            nodes=np.stack((x,y),axis=-1)
            for edge in (nodes[0],nodes[-1],nodes[:,0],nodes[:,-1]):edges.append((bid,edge))
        matches=[]
        for i,(a,u) in enumerate(edges):
            for b,v in edges[i+1:]:
                if a!=b and (np.allclose(u,v,rtol=0,atol=1e-13) or np.allclose(u,v[::-1],rtol=0,atol=1e-13)):matches.append((a,b))
        self.assertEqual(len(matches),3)
        self.assertEqual(set(a for pair in matches for a in pair),set(range(4)))
