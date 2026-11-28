import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from types import SimpleNamespace
import numpy as np
from matplotlib.figure import Figure
from mesh_interface_overlay import draw_interface_overlay

class InterfaceOverlayTests(unittest.TestCase):
    def result(self,kind):
        x,y=np.meshgrid([0.,1.],[0.,1.,2.],indexing='ij')
        return SimpleNamespace(blocks=[(x,y),(x+1,y)],diagnostics=dict(interface_problems=[dict(block_a=0,face_a='i_max',block_b=1,face_b='i_min',kind=kind)]))
    def test_nonconformal_draws_one_shared_face_with_halo_and_label(self):
        ax=Figure().subplots();result=self.result('nonconformal')
        draw_interface_overlay(ax,result,selected=True,custom=True)
        self.assertEqual(len(ax.lines),1)
        line=ax.lines[0];np.testing.assert_array_equal(line.get_xdata(),[1000]*3)
        self.assertEqual(line.get_color(),'#df001b');self.assertEqual(line.get_linestyle(),'-')
        self.assertEqual(len(line.get_path_effects()),2)
        self.assertEqual(ax.texts[0].get_text(),'С1')
        labels=[t.get_text() for t in ax.get_legend().texts]
        self.assertTrue(any('выбранный' in t for t in labels));self.assertTrue(any('настройки' in t for t in labels))
    def test_geometry_mismatch_draws_both_faces_and_no_warning_for_custom_only(self):
        ax=Figure().subplots();draw_interface_overlay(ax,self.result('geometry_mismatch'))
        self.assertEqual(len(ax.lines),2)
        self.assertTrue(all(line.get_color()=='#b500c5' for line in ax.lines))
        ax.clear();r=self.result('nonconformal');r.diagnostics['interface_problems']=[]
        draw_interface_overlay(ax,r,custom=True)
        self.assertEqual(len(ax.lines),0)

if __name__=='__main__':unittest.main()
