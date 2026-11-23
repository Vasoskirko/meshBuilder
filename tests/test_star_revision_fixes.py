import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest,tempfile,shutil,subprocess,json
from dataclasses import replace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow
from mesh_subchannel import export_subchannel_plot3d
from starccm_export_dialog import StarCcmExportDialog
from starccm_export_profile import validate_options,save_profile,load_profile
from starccm_macro_generator import generate_starccm_java_macro
from starccm_group_support import GROUP_SUPPORT

class RevisionFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        sid=next(i for i,s in w.model.subchannels.items() if s.sub_type=='interior')
        w.model.selected_subchannels={sid};w.switch_to_mesh_mode()
        w.base_params=replace(w.base_params,ni=8,nj=5,nz=2,z_len=.05)
        w.mesh_subpanel.apply_params(w.base_params)
        return w
    def test_axial_drafts_in_local_scope_block_export_and_rebuild_actual_xyz(self):
        for scope in ('template','block'):
            with self.subTest(scope=scope):
                w=self.window();p=w.mesh_subpanel
                with patch.object(w,'redraw_mesh_views'),patch.object(w,'populate_blocks_table'),patch('bundle_subchannel_builder.QMessageBox.critical') as error:
                    w.on_build_multiblock_mesh();self.assertTrue(w.can_export_mesh())
                    getattr(p,'radio_'+scope).setChecked(True)
                    # No editingFinished/valueChanged: simulate export with pending text.
                    p.fields['z_len'].setText('100');p.fields['nz'].lineEdit().setText('7')
                    self.assertFalse(w.can_export_mesh())
                    self.assertAlmostEqual(w.base_params.z_len,.1);self.assertEqual(w.base_params.nz,7)
                    w.on_build_multiblock_mesh();error.assert_not_called();self.assertTrue(w.can_export_mesh())
                    self.assertEqual((w.current_mesh_result.params.z_len,w.current_mesh_result.params.nz),(.1,7))
                    for radio in (p.radio_all,p.radio_template,p.radio_block):
                        radio.setChecked(True)
                        self.assertEqual(p.fields['nz'].value(),7);self.assertAlmostEqual(p.fields['z_len'].value(),.1)
                    with tempfile.TemporaryDirectory() as tmp:
                        path=Path(tmp)/'mesh.xyz';export_subchannel_plot3d(w.current_mesh_result,path)
                        words=path.read_text().split();nb=int(words[0]);dims=np.array(words[1:1+3*nb],dtype=int).reshape(nb,3)
                        self.assertTrue(np.all(dims[:,2]==8))
                        n=int(np.prod(dims[0]));coords=np.array(words[1+3*nb:],dtype=float)
                        self.assertAlmostEqual(coords[2*n:3*n].max(),.1)
    def test_fractional_time_step_profile_and_solver_parameter(self):
        w=self.window()
        with patch.object(w,'redraw_mesh_views'),patch.object(w,'populate_blocks_table'):w.on_build_multiblock_mesh()
        d=StarCcmExportDialog(mesh_result=w.current_mesh_result,bundle_model=w.model);self.addCleanup(d.deleteLater)
        d.rb_turb_srh.setChecked(True);d.field_time_step.setText('2.5e-5')
        options=d.read_options();self.assertEqual(options['time_step'],2.5e-5)
        d.field_time_step.setText('0,000025');self.assertEqual(d.read_options()['time_step'],2.5e-5)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';save_profile(options,path);saved=load_profile(path,1)
            self.assertEqual(saved['time_step'],2.5e-5)
        code=generate_starccm_java_macro('mesh.xyz',w.current_mesh_result,w.model,{}, {},options)
        self.assertIn('"TimeStep",2.5000000000000001e-05',code)
        self.assertIn('getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition("${TimeStep}")',code)
        self.assertIn('Dimensions.Builder().time(1).build()',code)
        self.assertIn('if (!reuse || timeParameter==null)',code)
        self.assertIn('no reinitialization',code)
        for value in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):validate_options(dict(options,time_step=value),1)
    def test_nested_group_membership_java_harness(self):
        java=shutil.which('java')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:self.skipTest('JDK compiler unavailable')
        fixture=Path(__file__).parent/'fixtures'/'star_group_harness.java'
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'CheckGroups.java';source.write_text(fixture.read_text().replace('// HELPERS',GROUP_SUPPORT))
            run=subprocess.run([java,str(source)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
