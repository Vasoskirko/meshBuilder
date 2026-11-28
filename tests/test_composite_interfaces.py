import unittest
from dataclasses import replace
import numpy as np
from mesh_composite_interfaces import CompositeInterface,InterfacePiece,partition_composite_interfaces,match_composite_interface


def block(edge):
    edge=np.asarray(edge,dtype=float)
    nodes=np.stack((edge,edge+np.array([0.,1.])),axis=1)
    return nodes[:,:,0],nodes[:,:,1]


class CompositeInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.blocks=[block([(x,0) for x in range(7)]),block([(x,0) for x in range(3)]),block([(x,0) for x in range(6,1,-1)])]
        self.interface=CompositeInterface(0,'j_min',(InterfacePiece(1,'j_min',0,2),InterfacePiece(2,'j_min',2,6,True)))

    def test_ranges_orientation_and_automatic_binding(self):
        conform,problems=partition_composite_interfaces(self.blocks,[self.interface],1e-12)
        self.assertEqual(conform,(self.interface,));self.assertFalse(problems)
        self.assertEqual(match_composite_interface(self.blocks,0,'j_min',[(2,'j_min'),(1,'j_min')],1e-12),self.interface)

    def test_holes_overlaps_reused_faces_and_bad_declarations_rejected(self):
        first,last=self.interface.pieces
        invalid=[replace(self.interface,pieces=(first,replace(last,start_a=3))),
                 replace(self.interface,pieces=(first,replace(last,start_a=1))),
                 replace(self.interface,pieces=(first,replace(last,stop_a=5))),
                 replace(self.interface,pieces=(first,replace(last,block_b=1))),
                 replace(self.interface,pieces=(replace(first,block_b=0),last)),
                 replace(self.interface,pieces=(replace(first,start_a=True),last))]
        for interface in invalid:
            with self.subTest(interface=interface),self.assertRaises(ValueError):partition_composite_interfaces(self.blocks,[interface],1e-12)
        with self.assertRaises(ValueError):partition_composite_interfaces(self.blocks,[self.interface,self.interface],1e-12)
        from mesh_core import BlockInterface
        with self.assertRaises(ValueError):
            partition_composite_interfaces(self.blocks,[self.interface],1e-12,pairwise=[BlockInterface(0,'j_min',1,'j_min',False)])
        for tol in (-1,float('nan'),True):
            with self.assertRaises(ValueError):partition_composite_interfaces(self.blocks,[self.interface],tol)

    def test_count_and_coordinate_mismatches_never_become_conformal(self):
        blocks=self.blocks.copy();blocks[1]=block([(0,0),(.5,0),(1,0),(2,0)])
        conform,problems=partition_composite_interfaces(blocks,[self.interface],1e-12)
        self.assertFalse(conform);self.assertEqual(problems[0]['kind'],'nonconformal')
        blocks[1]=block([(0,0),(1,.01),(2,0)])
        conform,problems=partition_composite_interfaces(blocks,[self.interface],1e-12)
        self.assertFalse(conform);self.assertEqual(problems[0]['kind'],'geometry_mismatch')
        with self.assertRaises(ValueError):match_composite_interface(blocks,0,'j_min',[(1,'j_min'),(2,'j_min')],1e-12)
        blocks[1]=block([(0,0),(float('nan'),0),(2,0)])
        with self.assertRaises(ValueError):partition_composite_interfaces(blocks,[self.interface],1e-12)

    def test_result_keeps_composite_metadata_and_unsupported_operations_refuse(self):
        from mesh_subchannel import SubchannelMeshResult,fill_subchannel_core
        from mesh_core import MeshParams
        from mesh_interface_diagnostics import require_star_conformity
        result=SubchannelMeshResult(MeshParams(),self.blocks,1,(),{},complete=False,
                                   composite_interfaces=(self.interface,))
        self.assertEqual(replace(result,diagnostics={'example':True}).composite_interfaces,(self.interface,))
        with self.assertRaisesRegex(ValueError,'составн'):require_star_conformity(result)
        with self.assertRaisesRegex(ValueError,'составн'):fill_subchannel_core(result,None)
        complete=replace(result,complete=True)
        self.assertIs(fill_subchannel_core(complete,None),complete)

    def test_actual_peripheral_rod_layer_to_internal_channel_on_six_sides(self):
        from bundle_geometry import BundleModel
        from meshbuilder.geometry.peripheral_mesh import build_peripheral_layered_preview
        from mesh_subchannel import build_mesh_from_bundle_model
        from mesh_core import MeshParams
        from mesh_interface_diagnostics import face_nodes
        m=BundleModel(s_flat=80)
        faces=('i_min','i_max','j_min','j_max')
        for sub in m.subchannels.values():
            if sub.sub_type!='peripheral':continue
            r1,r2=[m.rods[r] for r in sub.rod_ids]
            a,b=[np.array([r.x,r.y])*1e-3 for r in (r1,r2)]
            distance=np.linalg.norm(b-a);direction=(b-a)/distance
            half=(distance-(r1.diameter+r2.diameter)*.5e-3)/2
            neighbour=next(k for k,s in m.subchannels.items() if s.sub_type=='interior' and set(sub.rod_ids)<=set(s.rod_ids))
            internal=build_mesh_from_bundle_model(m,MeshParams(ni=33,nj=37,nz=1,law='uniform',mode='shape_count'),selected_sub_ids=[neighbour])
            preview=build_peripheral_layered_preview(m,sub.sub_id,33,33,rod_thickness=half*4/36,
                rod_cells=4,shell_thickness=.0003,hermite=True)
            blocks=internal.blocks+preview;offset=len(internal.blocks)
            for centre,rod,axis in ((a,r1,direction),(b,r2,-direction)):
                start=centre+rod.diameter*.5e-3*axis
                expected=start+np.linspace(0,half,37)[:,None]*axis
                masters=[(bid,face) for bid,block in enumerate(internal.blocks) for face in faces
                         if (lambda edge:edge.shape==expected.shape and (np.allclose(edge,expected,rtol=0,atol=1e-13) or np.allclose(edge[::-1],expected,rtol=0,atol=1e-13)))(face_nodes(block,face))]
                self.assertEqual(len(masters),1)
                candidates=[]
                for bid,block in enumerate(preview):
                    for face in faces:
                        edge=face_nodes(block,face);along=(edge-start)@axis
                        perpendicular=edge-start-along[:,None]*axis
                        if np.max(np.linalg.norm(perpendicular,axis=1))<1e-12 and along.min()>-1e-12 and along.max()<half+1e-12:
                            candidates.append((offset+bid,face))
                self.assertEqual(len(candidates),2)
                interface=match_composite_interface(blocks,*masters[0],candidates,1e-12)
                conform,problems=partition_composite_interfaces(blocks,[interface],1e-12)
                self.assertEqual(len(conform),1);self.assertFalse(problems)
                self.assertEqual(sum(p.stop_a-p.start_a for p in interface.pieces),36)
