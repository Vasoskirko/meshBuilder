import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys,unittest,tempfile,json
from dataclasses import replace
from copy import deepcopy
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from bundle_subchannel_builder import BundleBuilderWindow
from bundle_project import capture_project,save_project,load_project,validate_project,BundleProjectError,geometry
from starccm_export_profile import DEFAULTS,validate_options
from yplus_calculator import FLUID_MODES
from fluid_properties import GAS_PRESETS

class BundleProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def window(self):
        w=BundleBuilderWindow();self.addCleanup(w.deleteLater)
        return w
    def configured(self):
        w=self.window();m=w.model
        sid=next(i for i,s in m.subchannels.items() if s.sub_type=='interior')
        selected_rods=set(m.subchannels[sid].rod_ids)
        other=[r for i,r in m.rods.items() if i not in selected_rods]
        c=(other[0].q,other[0].r);m.user_custom_diameters[c]=8.7
        m.user_rod_types[(0,0)]='guide'
        m.user_deleted_coords={(other[-1].q,other[-1].r)}
        m.auto_deleted_clash_coords={(other[-2].q,other[-2].r)}
        m.update_geometry();m.selected_subchannels={next(i for i,s in m.subchannels.items() if s.sub_type=='interior')}
        w.base_params=replace(w.base_params,ni=8,nj=12,nz=3,z_len=.08,law='wall_core',mode='layer_first_growth',wall_layers=4,h1=5e-6,layer_growth=1.1)
        p=w.mesh_subpanel;p.apply_params(w.base_params);w.switch_to_mesh_mode()
        tid=p.combo_templates.currentData();gid=p.combo_blocks.currentData()
        w.template_configs={p.combo_templates.itemData(i):replace(w.base_params,h1=4e-6) for i in range(p.combo_templates.count())}
        w.block_custom_configs[gid]=replace(w.template_configs[tid],max_auto_cells=7000)
        p.radio_block.setChecked(True)
        p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('fixed_count'));p.combo_core_lines.setCurrentIndex(1)
        p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData('aspect_alignment'))
        p.fields['core_growth'].setValue(1.2);p.fields['core_max_size'].setValue(.0002)
        p.fields['core_layers'].setValue(17);p.cu.setCurrentText('мм')
        p.yplus_saved_state=dict(fluid_mode=FLUID_MODES[-1],gas=next(iter(GAS_PRESETS)),temp_c='300',press_mpa='15',density='1000',dyn_vis='0.001',re='50000',vel='5.62',flow='0.15',yplus='1',flow_mode='reynolds',conductivity_model='background')
        w.star_export_options=validate_options(dict(DEFAULTS,turbulence_model='hybrid_srh',time_step=2.5e-5,selected_subchannels=[1],subchannel_reports=['geometry'],time_mean_fields=['velocity']))
        w.tabs.setCurrentIndex(2);w.combo_detail.setCurrentIndex(w.combo_detail.findData(4))
        return w
    def test_full_roundtrip_including_unselected_rods_overrides_and_export(self):
        w=self.configured();project=capture_project(w)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'проект.json';save_project(project,path);loaded=load_project(path)
        other=self.window();other.apply_bundle_project(loaded)
        actual=capture_project(other)
        self.assertEqual(actual.data,project.data)
        self.assertEqual(geometry(other.model),geometry(w.model))
        self.assertTrue(other.mesh_subpanel.last_yplus_result)
        self.assertFalse(other.can_export_mesh());self.assertIsNone(other.current_layer_result)
        self.assertEqual(other.table_blocks.rowCount(),0)
        self.assertFalse(other.mesh_subpanel.btn_export_star.isEnabled())
        with patch.object(other,'redraw_mesh_views'),patch.object(other,'populate_blocks_table'),patch('bundle_subchannel_builder.QMessageBox.information'),patch('bundle_subchannel_builder.QMessageBox.critical') as error:
            other.on_build_layer_only();other.on_fill_core_clicked();error.assert_not_called()
        self.assertTrue(other.can_export_mesh())
        capture_project(other)
        self.assertTrue(other.can_export_mesh(),'Saving unchanged inputs invalidated the mesh')
        with patch('starccm_export_dialog.StarCcmExportDialog') as dialog:
            other.on_export_starccm_dialog()
            dialog.return_value.apply_options.assert_called_once_with(project.data['export'])
            dialog.return_value.exec.assert_called_once()
    def test_pending_axial_and_geometry_inputs_saved_without_old_mesh(self):
        w=self.configured();p=w.mesh_subpanel
        p.fields['z_len'].setText('120');p.fields['nz'].lineEdit().setText('7')
        old_pitch=w.model.pitch;w.pitch_spin.lineEdit().setText('13.5')
        data=capture_project(w)
        self.assertEqual(data.base.nz,7);self.assertAlmostEqual(data.base.z_len,.12)
        other=self.window();other.apply_bundle_project(data)
        self.assertAlmostEqual(other.pitch_spin.value(),13.5);self.assertEqual(other.model.pitch,old_pitch)
        self.assertFalse(other.can_export_mesh())
        self.assertIn('неприменённые',other.mesh_console.toPlainText())
    def test_invalid_load_is_transactional_and_rejects_bad_bindings_versions(self):
        w=self.configured();project=capture_project(w);original=w.model
        cases=[]
        data=deepcopy(project.data);data['version']=999;cases.append(data)
        data=deepcopy(project.data);data['mesh']['core']['mode']='unknown';cases.append(data)
        data=deepcopy(project.data);next(iter(data['mesh']['blocks'].values()))['binding'][0]+=1;cases.append(data)
        data=deepcopy(project.data);data['mesh']['base']['nz']=True;cases.append(data)
        data=deepcopy(project.data);data['mesh']['base']['nj']=1;cases.append(data)
        data=deepcopy(project.data);data['geometry']['lattice']['pitch']=float('nan');cases.append(data)
        data=deepcopy(project.data);data['geometry']['selected'][0]['rods'][0][0]+=1;cases.append(data)
        for data in cases:
            broken=deepcopy(project);broken.data=data
            with self.assertRaises(ValueError):w.apply_bundle_project(broken)
            self.assertIs(w.model,original)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json'
            for text in ('{"format":"x","format":"y"}','{"value": NaN}','[]'):
                path.write_text(text)
                with self.assertRaises(ValueError):load_project(path)
    def test_atomic_save_and_invalid_draft_preserve_existing_file(self):
        w=self.configured();project=capture_project(w)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'project.json';path.write_text('ORIGINAL')
            with patch('bundle_project.os.replace',side_effect=OSError('disk')):
                with self.assertRaises(OSError):save_project(project,path)
            self.assertEqual(path.read_text(),'ORIGINAL');self.assertEqual(len(list(Path(tmp).iterdir())),1)
            w.project_path=path;w.mesh_subpanel.fields['h1'].setText('invalid')
            with patch('bundle_subchannel_builder.QMessageBox.warning') as warning:w.on_save_json()
            warning.assert_called_once();self.assertEqual(path.read_text(),'ORIGINAL')
    def test_legacy_section_import_and_empty_project(self):
        w=self.configured()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.json';path.write_text(json.dumps(w.model.export_dict()))
            legacy=load_project(path);self.assertTrue(legacy.legacy)
            other=self.window()
            with patch('bundle_subchannel_builder.QFileDialog.getOpenFileName',return_value=(str(path),'')):
                other.on_load_json()
            self.assertEqual(other.model.selected_subchannels,w.model.selected_subchannels)
            self.assertIsNone(other.project_path);self.assertFalse(other.can_export_mesh())
            self.assertIn('старый JSON',other.mesh_console.toPlainText())
        empty=self.window();project=capture_project(empty)
        other=self.window();other.apply_bundle_project(project)
        self.assertFalse(other.model.selected_subchannels);self.assertFalse(other.can_export_mesh())
    def test_busy_load_and_export_preferences_recorded_on_close(self):
        w=self.configured();w._mesh_thread=object()
        with patch('bundle_subchannel_builder.QMessageBox.warning'),patch('bundle_subchannel_builder.QFileDialog.getOpenFileName') as chooser:w.on_load_json();chooser.assert_not_called()
        w._mesh_thread=None
        from starccm_export_dialog import StarCcmExportDialog
        d=StarCcmExportDialog(w,mesh_result=None);self.addCleanup(d.deleteLater)
        d.rb_turb_srh.setChecked(True);d.field_time_step.setText('0.00025');d.reject()
        self.assertEqual(w.star_export_options['time_step'],.00025)

    def test_invalid_calculator_draft_does_not_restore_reference_results(self):
        w=self.configured();project=capture_project(w)
        for field in ('density','re','temp_c'):
            with self.subTest(field=field):
                broken=deepcopy(project);broken.data['calculator'][field]='nan'
                other=self.window();other.apply_bundle_project(broken)
                self.assertEqual(other.mesh_subpanel.yplus_saved_state[field],'nan')
                self.assertFalse(other.mesh_subpanel.last_yplus_result)
                self.assertFalse(other.mesh_subpanel.current_fluid_props)
