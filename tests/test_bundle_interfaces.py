from dataclasses import replace
from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model, fill_subchannel_core

class BundleInterfacesTests(unittest.TestCase):
    def setUp(self):
        self.model=BundleModel(s_flat=65,pitch=12.75,d_fuel=9.1,d_guide=12,d_instrument=10.3)
        sid=next(k for k,s in self.model.subchannels.items() if s.sub_type=='interior')
        self.model.selected_subchannels={sid}
        self.p=MeshParams(ni=8,nj=10,nz=1,law='uniform',mode='shape_count')
    def test_incompatible_global_or_interface_inputs_rejected(self):
        for changes in (dict(ni=10),dict(nz=2),dict(z_len=.2),dict(nj=12)):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError,'совпадать|стык|ni'):
                build_mesh_from_bundle_model(self.model,self.p,block_custom_overrides={1:replace(self.p,**changes)})
    def test_valid_complete_and_layer_fill(self):
        self.assertTrue(build_mesh_from_bundle_model(self.model,self.p).complete)
        p=replace(self.p,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        layer=build_mesh_from_bundle_model(self.model,p)
        self.assertFalse(layer.complete)
        full=fill_subchannel_core(layer,self.model,core_mode='fixed_count',core_layers=3)
        self.assertTrue(full.complete)
        from mesh_subchannel import _validate_interfaces
        _validate_interfaces(full.blocks,full.interfaces,p.pitch*1e-11)
    def test_damaged_layer_rejected_before_fill(self):
        p=replace(self.p,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6)
        layer=build_mesh_from_bundle_model(self.model,p)
        blocks=list(layer.blocks);blocks[0]=tuple(v[:-1] for v in blocks[0])
        with self.assertRaisesRegex(ValueError,'ni'):
            fill_subchannel_core(replace(layer,blocks=blocks),self.model)
    def test_multiple_subchannels(self):
        self.model.selected_subchannels=set(k for k,s in self.model.subchannels.items() if s.sub_type=='interior')
        self.assertTrue(build_mesh_from_bundle_model(self.model,self.p).complete)
