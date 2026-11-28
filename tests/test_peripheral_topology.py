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

    def test_clustering_hermite_and_measured_wall_resolution(self):
        from meshbuilder.geometry.peripheral_mesh import peripheral_wall_metrics
        m=BundleModel(s_flat=80)
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            regular=build_peripheral_preview(m,sub.sub_id,33,33)
            straight=peripheral_wall_metrics(m,sub.sub_id,regular)
            for hermite in (False,True):
                blocks=build_peripheral_preview(m,sub.sub_id,33,33,clustering=2,hermite=hermite)
                measured=peripheral_wall_metrics(m,sub.sub_id,blocks)
                for kind in ('rods','shell'):
                    self.assertGreater(measured[kind]['normal_m'][0],0)
                    self.assertLess(measured[kind]['edge_m'][1],straight[kind]['edge_m'][1]/3)
                    if hermite:self.assertLess(measured[kind]['median_angle_deg'],straight[kind]['median_angle_deg'])
                # Each curved block boundary remains identical to its neighbour.
                edges=[]
                for bid,(x,y) in enumerate(blocks):
                    points=np.stack((x,y),-1)
                    edges.extend((bid,e) for e in (points[0],points[-1],points[:,0],points[:,-1]))
                count=sum(a!=b and (np.allclose(u,v,rtol=0,atol=1e-13) or np.allclose(u,v[::-1],rtol=0,atol=1e-13))
                          for i,(a,u) in enumerate(edges) for b,v in edges[i+1:])
                self.assertEqual(count,3)
        sid=next(k for k,s in m.subchannels.items() if s.sub_type=='peripheral')
        for strength in (-1,7,float('nan'),float('inf'),True,'2'):
            with self.assertRaises(ValueError):build_peripheral_preview(m,sid,clustering=strength)

    def test_separate_shell_layer_is_normal_and_conformal(self):
        from meshbuilder.geometry.peripheral_mesh import peripheral_wall_metrics
        m=BundleModel(s_flat=80)
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            blocks=build_peripheral_preview(m,sub.sub_id,33,33,clustering=2,hermite=True,
                                            shell_thickness=.0003,shell_cells=6,shell_growth=1.2)
            self.assertEqual(len(blocks),6)
            total=0.
            for x,y in blocks:
                xx=np.stack((x[:-1,:-1],x[1:,:-1],x[1:,1:],x[:-1,1:]),-1)
                yy=np.stack((y[:-1,:-1],y[1:,:-1],y[1:,1:],y[:-1,1:]),-1)
                total+=np.sum(xx*np.roll(yy,-1,-1)-yy*np.roll(xx,-1,-1))/2
            self.assertLess(abs(total*1e6-sub.a_fluid_mm2)/sub.a_fluid_mm2,4e-4)
            measured=peripheral_wall_metrics(m,sub.sub_id,blocks)
            expected=.0003/sum(1.2**k for k in range(6))
            for value in measured['shell']['normal_m']:self.assertAlmostEqual(value,expected,delta=1e-14)
            self.assertLess(measured['shell']['angle_deg'][1],1e-5)
            for x,y in blocks[4:]:
                widths=np.hypot(np.diff(x,axis=1),np.diff(y,axis=1))
                np.testing.assert_allclose(widths[:,1:]/widths[:,:-1],1.2,rtol=1e-10)
            edges=[]
            for bid,(x,y) in enumerate(blocks):
                points=np.stack((x,y),-1)
                edges.extend((bid,e) for e in (points[0],points[-1],points[:,0],points[:,-1]))
            matches=0
            for i,(a,u) in enumerate(edges):
                for b,v in edges[i+1:]:
                    if a!=b and u.shape==v.shape and (np.allclose(u,v,rtol=0,atol=1e-13) or np.allclose(u,v[::-1],rtol=0,atol=1e-13)):matches+=1
            self.assertEqual(matches,6)
        sid=next(k for k,s in m.subchannels.items() if s.sub_type=='peripheral')
        for kwargs in ({'shell_thickness':1},{'shell_thickness':float('nan')},{'shell_cells':0},{'shell_growth':.9}):
            with self.assertRaises(ValueError):build_peripheral_preview(m,sid,**kwargs)

    def test_inherited_gap_nodes_match_existing_internal_builder(self):
        from mesh_subchannel import build_mesh_from_bundle_model
        from mesh_core import MeshParams
        m=BundleModel(s_flat=80)
        def edges(blocks):
            return [e for x,y in blocks for p in [np.stack((x,y),-1)]
                    for e in (p[0],p[-1],p[:,0],p[:,-1])]
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            neighbours=[k for k,s in m.subchannels.items() if s.sub_type=='interior' and set(sub.rod_ids)<=set(s.rod_ids)]
            self.assertEqual(len(neighbours),1)
            internal=build_mesh_from_bundle_model(m,MeshParams(ni=33,nj=33,nz=1,law='uniform',mode='shape_count'),selected_sub_ids=neighbours)
            # Keep clustered core and shell, but inherit the uniform neighbour's gap profile.
            preview=build_peripheral_preview(m,sub.sub_id,33,33,clustering=2,hermite=True,shell_thickness=.0003,
                                            gap_distributions={rid:np.linspace(0,1,33) for rid in sub.rod_ids})
            matches=sum(u.shape==v.shape and (np.allclose(u,v,rtol=0,atol=1e-13) or np.allclose(u,v[::-1],rtol=0,atol=1e-13))
                        for u in edges(preview) for v in edges(internal.blocks))
            self.assertEqual(matches,2)
        sid=sub.sub_id if sub.sub_type=='peripheral' else next(k for k,s in m.subchannels.items() if s.sub_type=='peripheral')
        for values in ({},{rid:[0,1] for rid in m.subchannels[sid].rod_ids}):
            with self.assertRaises(ValueError):build_peripheral_preview(m,sid,gap_distributions=values)
