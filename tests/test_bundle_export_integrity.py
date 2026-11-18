from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_core import MeshParams
from mesh_quality import read_plot3d_ascii
from mesh_subchannel import export_subchannel_plot3d

class BundleExportTests(unittest.TestCase):
    def test_incomplete_export_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mesh.xyz';path.write_text('ORIGINAL')
            with self.assertRaises(ValueError):export_subchannel_plot3d(SimpleNamespace(complete=False),path)
            self.assertEqual(path.read_text(),'ORIGINAL')
            self.assertEqual(list(Path(tmp).iterdir()),[path])
    def test_real_export_and_failed_replace(self):
        x,y=np.meshgrid([0.,1.],[0.,1.],indexing='ij')
        r=SimpleNamespace(complete=True,params=MeshParams(ni=2,nj=2,nz=1),blocks=[(x,y)])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mesh.xyz';export_subchannel_plot3d(r,path)
            a=read_plot3d_ascii(path)[0]
            np.testing.assert_array_equal(a[:,:,0,0],x)
            original=path.read_bytes()
            with patch('mesh_subchannel.os.replace',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):export_subchannel_plot3d(r,path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(tmp).iterdir()),[path])
