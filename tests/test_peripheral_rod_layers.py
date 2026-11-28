import unittest
import numpy as np
from bundle_geometry import BundleModel
from meshbuilder.geometry.peripheral_mesh import build_peripheral_layered_preview,peripheral_wall_metrics


def block_edges(blocks):
    return [(bid,e) for bid,(x,y) in enumerate(blocks) for p in [np.stack((x,y),-1)]
            for e in (p[0],p[-1],p[:,0],p[:,-1])]


class PeripheralRodLayerTests(unittest.TestCase):
    def test_all_wall_rotations_normal_layers_area_growth_and_shared_nodes(self):
        m=BundleModel(s_flat=80)
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            for shell in (0.,.0003):
                with self.subTest(side=sub.wall_side,shell=shell):
                    blocks=build_peripheral_layered_preview(m,sub.sub_id,33,33,rod_thickness=.0002,
                        rod_cells=6,rod_growth=1.2,shell_thickness=shell,shell_cells=6,clustering=2,hermite=True)
                    self.assertEqual(len(blocks),10 if shell else 8)
                    stats=peripheral_wall_metrics(m,sub.sub_id,blocks)
                    expected=.0002/sum(1.2**k for k in range(6))
                    for h in stats['rods']['normal_m']:self.assertAlmostEqual(h,expected,delta=1e-14)
                    self.assertLess(stats['rods']['angle_deg'][1],1e-5)
                    if shell:self.assertLess(stats['shell']['angle_deg'][1],1e-5)
                    for x,y in blocks[-4:]:
                        widths=np.hypot(np.diff(x,axis=1),np.diff(y,axis=1))
                        np.testing.assert_allclose(widths[:,1:]/widths[:,:-1],1.2,rtol=1e-9)
                    edges=block_edges(blocks)
                    matches=sum(a!=b and u.shape==v.shape and (np.allclose(u,v,rtol=0,atol=1e-13) or np.allclose(u,v[::-1],rtol=0,atol=1e-13))
                                for i,(a,u) in enumerate(edges) for b,v in edges[i+1:])
                    self.assertEqual(matches,12 if shell else 9)
                    total=0.
                    for x,y in blocks:
                        xx=np.stack((x[:-1,:-1],x[1:,:-1],x[1:,1:],x[:-1,1:]),-1)
                        yy=np.stack((y[:-1,:-1],y[1:,:-1],y[1:,1:],y[:-1,1:]),-1)
                        area=(xx*np.roll(yy,-1,-1)-yy*np.roll(xx,-1,-1)).sum(-1)/2
                        self.assertTrue(np.all(area>0));total+=area.sum()
                    self.assertLess(abs(total*1e6-sub.a_fluid_mm2)/sub.a_fluid_mm2,4e-4)

    def test_invalid_overlapping_layers_preserve_original_model(self):
        m=BundleModel(s_flat=80);sid=next(k for k,s in m.subchannels.items() if s.sub_type=='peripheral')
        before=m.export_dict()
        for kwargs in ({'rod_thickness':0},{'rod_thickness':float('nan')},{'rod_thickness':.01},
                       {'rod_thickness':.0002,'shell_thickness':.01},
                       {'rod_thickness':.0002,'rod_cells':True},{'rod_thickness':.0002,'rod_growth':.9}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):build_peripheral_layered_preview(m,sid,**kwargs)
            self.assertEqual(m.export_dict(),before)
        build_peripheral_layered_preview(m,sid,rod_thickness=.0002)
        self.assertEqual(m.export_dict(),before)

    def test_split_gap_face_matches_existing_internal_mesh(self):
        from mesh_core import MeshParams
        from mesh_subchannel import build_mesh_from_bundle_model
        m=BundleModel(s_flat=80)
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            r1,r2=[m.rods[r] for r in sub.rod_ids]
            a,b=[np.array([r.x,r.y])*1e-3 for r in (r1,r2)]
            distance=np.linalg.norm(b-a);tangent=(b-a)/distance
            half=(distance-(r1.diameter+r2.diameter)*.5e-3)/2
            thickness=half*4/36
            preview=build_peripheral_layered_preview(m,sub.sub_id,33,33,rod_thickness=thickness,rod_cells=4,
                shell_thickness=.0003,hermite=True)
            neighbour=next(k for k,s in m.subchannels.items() if s.sub_type=='interior' and set(sub.rod_ids)<=set(s.rod_ids))
            internal=build_mesh_from_bundle_model(m,MeshParams(ni=33,nj=37,nz=1,law='uniform',mode='shape_count'),selected_sub_ids=[neighbour])
            for centre,r,direction in ((a,r1,tangent),(b,r2,-tangent)):
                start=centre+r.diameter*.5e-3*direction
                expected=start+np.linspace(0,half,37)[:,None]*direction
                # The external face is split across a rod-layer block and a core block.
                found=[]
                for _,edge in block_edges(preview):
                    along=(edge-start)@direction
                    perpendicular=edge-start-along[:,None]*direction
                    if np.max(np.linalg.norm(perpendicular,axis=1))<1e-12 and along.min()>-1e-12 and along.max()<half+1e-12:
                        found.extend(edge)
                actual=np.unique(np.round(np.asarray(found),14),axis=0)
                actual=actual[np.argsort((actual-start)@direction)]
                self.assertEqual(actual.shape,expected.shape)
                np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-13)
                self.assertTrue(any(edge.shape==expected.shape and (np.allclose(edge,expected,rtol=0,atol=1e-13) or np.allclose(edge[::-1],expected,rtol=0,atol=1e-13)) for _,edge in block_edges(internal.blocks)))
