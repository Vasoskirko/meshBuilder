import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import replace
from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from mesh_core import MeshParams
from mesh_project import MeshProject, merge_project_inputs, save_project, load_project, rebuild_project
from mesh_gui import MeshWindow
import numpy as np

class ProjectInputsTests(unittest.TestCase):
    def test_each_wall_mode_preserves_active_edits_roundtrip(self):
        for mode, changes in [('layer_first_growth',dict(h1=8e-6,layer_growth=1.2)),
                ('layer_thickness',dict(h1=8e-6,layer_thickness=200e-6)),
                ('layer_growth',dict(layer_growth=1.2,layer_thickness=200e-6))]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base=MeshParams(law='wall_core',mode=mode,ni=8,nz=1,wall_layers=4,h1=5e-6,layer_thickness=100e-6)
                current=replace(base,**changes)
                merged=merge_project_inputs(base,current)
                for k,v in changes.items():self.assertEqual(getattr(merged,k),v)
                path=Path(tmp)/'project.json'
                project=MeshProject(merged,build_target='layer_only')
                save_project(project,path)
                for a,b in zip(rebuild_project(MeshProject(current,build_target='layer_only')).blocks,rebuild_project(load_project(path)).blocks):
                    for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
    def test_loaded_gui_reads_unfinished_text_before_save(self):
        app=QApplication.instance() or QApplication([])
        window=MeshWindow()
        try:
            p=MeshParams(law='wall_core',mode='layer_first_growth',h1=5e-6,wall_layers=4,ni=8,nz=1)
            window.apply_project(MeshProject(p,build_target='layer_only'))
            window.fields['h1'].setText('8')
            window.fields['layer_growth'].setText('1.2')
            project=window.read_project()
            self.assertAlmostEqual(project.params.h1,8e-6)
            self.assertAlmostEqual(project.params.layer_growth,1.2)
            self.assertFalse(window.layer_growthrow.isHidden())
            self.assertTrue(window.layer_thicknessrow.isHidden())
        finally:window.deleteLater()
