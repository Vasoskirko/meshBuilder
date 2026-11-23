"""The streaming report retains eager counts, locations and threshold semantics."""
import gc
import unittest
import weakref
from dataclasses import replace
import numpy as np
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from bundle_mesh_jobs import analyse_subchannel_result
import mesh_quality as q


class QualityStreamingTests(unittest.TestCase):
    def result(self, layer=False):
        model=BundleModel()
        model.selected_subchannels=set(list(i for i,s in model.subchannels.items() if s.sub_type=='interior')[:3])
        p=MeshParams(ni=8,nj=10,nz=4)
        if layer:p=replace(p,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        return build_mesh_from_bundle_model(model,p)

    def test_gui_stream_matches_eager_full_and_layer_reports(self):
        for layer in (False,True):
            result=self.result(layer)
            progress=[]
            streamed=analyse_subchannel_result(result,lambda f,t:progress.append(f))
            blocks=q.blocks_from_result(result)
            interfaces=[(i.block_a,i.face_a,i.block_b,i.face_b,i.reversed) for i in result.interfaces if result.complete or not i.face_a.startswith('j_')]
            eager=q.analyse_blocks(blocks,interfaces=interfaces)
            self.assertEqual(streamed,eager)
            self.assertEqual(progress,sorted(progress))

    def test_stream_profiles_thresholds_and_nonuniform_3d_match_eager(self):
        x,y,z=np.meshgrid(np.linspace(0,1,5),np.linspace(0,1,6),[0,.1,.4,1.],indexing='ij')
        a=np.stack((x+.04*y*z,y,z),axis=-1)
        b=a.copy();b[...,0]*=-1 # invalid orientation must still be counted
        blocks=[a,b]
        options=dict(interfaces=[],tolerance=1e-10,thresholds={'scaled_jacobian':.95,'neighbor_volume_ratio':2})
        self.assertEqual(q.analyse_blocks(iter(blocks),block_count=2,**options),q.analyse_blocks(blocks,**options))
        profile={'scaled_jacobian':{'caution':.98,'risk':.9},'aspect_ratio':{'caution':3,'risk':8}}
        self.assertEqual(q.analyse_blocks(iter(blocks),block_count=2,profile=profile,interfaces=[],tolerance=1e-10),q.analyse_blocks(blocks,profile=profile,interfaces=[],tolerance=1e-10))

    def test_consumed_block_coordinates_are_not_retained(self):
        refs=[]
        def blocks():
            for i in range(8):
                gc.collect()
                if i>1:self.assertIsNone(refs[i-2]())
                x,y,z=np.meshgrid([0.,1.],[0.,1.],[0.,1.],indexing='ij')
                block=np.stack((x,y,z),axis=-1)
                refs.append(weakref.ref(block))
                yield block
        report=q.analyse_blocks(blocks(),block_count=8,interfaces=[],tolerance=1e-10)
        self.assertEqual(report['totals']['cells'],8)

    def test_stream_rejects_missing_metadata_and_wrong_counts(self):
        block=np.stack(np.meshgrid([0.,1.],[0.,1.],[0.,1.],indexing='ij'),axis=-1)
        for options in (dict(block_count=1),dict(block_count=1,interfaces=[]),dict(block_count=0,interfaces=[],tolerance=0)):
            with self.assertRaises(q.QualityError):q.analyse_blocks(iter([block]),**options)
        for count in (1,3):
            with self.assertRaises(q.QualityError):q.analyse_blocks(iter([block,block]),block_count=count,interfaces=[],tolerance=0)

    def test_cancel_during_quality_does_not_return_partial_report(self):
        result=self.result()
        def cancel(f,t):
            if f>60:raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):analyse_subchannel_result(result,cancel)


if __name__=='__main__':unittest.main()
