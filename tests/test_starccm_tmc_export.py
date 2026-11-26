import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from starccm_export_dialog import StarCcmExportDialog
from starccm_export_profile import DEFAULTS,validate_options,save_profile,load_profile
from starccm_tmc_export import TMC_DEFAULTS,canonical_tmc_options,validate_tmc_settings,reference_geometry,render_tmc_macro,bundle_names,write_tmc_bundle,_publish
from mesh_export_jobs import ExportCancelled

class TmcExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.model=BundleModel(pitch=11.64);cls.model.selected_subchannels={18,22}
        cls.result=build_mesh_from_bundle_model(cls.model,MeshParams(ni=45,nj=50,nz=2,z_len=.3))
    def test_reference_contract_rejects_other_geometry(self):
        self.assertGreater(reference_geometry(self.result,self.model)['area'],0)
        model=deepcopy(self.model);model.pitch=12.75
        with self.assertRaises(ValueError):reference_geometry(self.result,model)
    def test_settings_profiles_and_template(self):
        settings=dict(TMC_DEFAULTS,time_step=1.2e-5,blocks_to_run=3)
        options=dict(DEFAULTS,workflow=dict(DEFAULTS['workflow'],tdc_enabled=True,tdc_equivalence=True))
        options.update(canonical_tmc_options(settings));options.update(export_mode='tmc_reference',tmc_settings=settings)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';save_profile(options,path)
            self.assertEqual(load_profile(path,2),validate_options(options,2))
        bad=deepcopy(options);bad['initialize_solution']=True
        with self.assertRaises(ValueError):validate_options(bad,2)
        for changes in ({'mu':float('nan')},{'rho':True},{'blocks_to_run':1.5},{'heat_flux_2':1},{'unknown':3}):
            with self.assertRaises(ValueError):validate_tmc_settings(changes)
        source=render_tmc_macro(settings)
        self.assertIn('param("BlocksToRun",3,',source)
        self.assertIn('public class TMC_Hybrid',source)
        self.assertEqual(validate_options({})['export_mode'],'general')
    def test_unified_tdc_shared_settings_roundtrip(self):
        dialog=StarCcmExportDialog(mesh_result=self.result,bundle_model=self.model)
        try:
            dialog.rb_inter_fuse.setChecked(True);dialog.rb_turb_srh.setChecked(True)
            dialog.tdc_enabled.setChecked(True);dialog.tdc_equivalence.setChecked(True);dialog.heat_enabled.setChecked(True)
            dialog.field_time_step.setText('invalid')
            with self.assertRaises(ValueError):dialog.read_options()
            dialog.field_time_step.setValue(1.2e-5)
            options=dialog.read_options()
            self.assertEqual(options['time_step'],1.2e-5)
            self.assertFalse(options['initialize_solution'])
            dialog.apply_options(options);self.assertEqual(dialog.read_options(),options)
            self.assertEqual(dialog.tabs.count(),8)
        finally:dialog.deleteLater();self.app.processEvents()
    @staticmethod
    def xyz(result,path,**kwargs):Path(path).write_text('XYZ sentinel')
    def test_six_files_generated_and_cancel_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp,patch('mesh_subchannel.export_subchannel_plot3d',side_effect=self.xyz):
            targets=write_tmc_bundle(tmp,'mesh.xyz',self.result,self.model,TMC_DEFAULTS,lambda *a:None)
            self.assertEqual(len(targets),6)
            base=targets[1].read_text();control=targets[2].read_text()
            self.assertIn('Subchannel_1_Domain',base);self.assertIn('Gap_Sub1_Sub2',base)
            self.assertIn('public class TMC_Hybrid',control)
            self.assertIn('Initialize',targets[4].read_text())
            originals={p:p.read_bytes() for p in targets}
            def cancel(value,text):
                if value==95:raise ExportCancelled()
            with self.assertRaises(ExportCancelled):write_tmc_bundle(tmp,'mesh.xyz',self.result,self.model,TMC_DEFAULTS,cancel)
            self.assertEqual({p:p.read_bytes() for p in targets},originals)
            self.assertFalse(list(Path(tmp).glob('.tmc_*')))
    def test_publish_failure_rolls_back_and_failed_restore_keeps_backup(self):
        import starccm_tmc_export as module
        real_replace=module.os.replace
        for failed_restore in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);targets=[root/'one',root/'two'];staged={}
                for target in targets:
                    target.write_text('old');temp=root/(target.name+'.tmp');temp.write_text('new');staged[target]=temp
                calls=0
                def replace(src,dst):
                    nonlocal calls
                    calls+=1
                    if calls==2 or (failed_restore and calls==3):raise OSError('injected failure')
                    return real_replace(src,dst)
                with patch.object(module.os,'replace',side_effect=replace),self.assertRaises(OSError):_publish(staged)
                if failed_restore:
                    backups=list(root.glob('.tmc_backup_*'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(),'old')
                else:self.assertTrue(all(p.read_text()=='old' for p in targets));self.assertFalse(list(root.glob('.tmc_backup_*')))
    def test_invalid_filename(self):
        for name in ('../mesh.xyz','a\\mesh.xyz','mesh.java','bad\n.xyz'):
            with self.assertRaises(ValueError):bundle_names(name)
    def test_ui_export_calls_bundle_and_stale_mesh_blocks_before_chooser(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWidget
        parent=QWidget();parent.current_mesh_result=self.result;parent.can_export_mesh=lambda:True
        dialog=StarCcmExportDialog(parent,mesh_result=self.result,bundle_model=self.model)
        try:
            dialog.rb_inter_fuse.setChecked(True);dialog.rb_turb_srh.setChecked(True);dialog.tdc_enabled.setChecked(True);dialog.tdc_equivalence.setChecked(True);dialog.heat_enabled.setChecked(True)
            with tempfile.TemporaryDirectory() as tmp,patch('starccm_unified_export.QFileDialog.getExistingDirectory',return_value=tmp) as chooser,patch('starccm_unified_export.write_tmc_bundle',return_value=[]) as writer,patch('starccm_unified_export.QMessageBox.information'),patch.object(dialog,'accept') as accepted:
                dialog.generate_and_save();writer.assert_called_once();accepted.assert_called_once()
                parent.can_export_mesh=lambda:False
                with patch('starccm_unified_export.QMessageBox.warning') as warning:
                    dialog.generate_and_save();warning.assert_called_once()
                self.assertEqual(chooser.call_count,1)
        finally:dialog.deleteLater();parent.deleteLater();self.app.processEvents()
