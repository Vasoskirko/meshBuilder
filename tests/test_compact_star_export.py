"""Compact Qt controls, geometry identities and actual generated assignments."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from PySide6.QtWidgets import QApplication,QWidget
from bundle_geometry import BundleModel
from mesh_core import MeshParams
from mesh_subchannel import build_mesh_from_bundle_model
from starccm_export_dialog import StarCcmExportDialog
from starccm_export_profile import save_profile,load_profile
from starccm_macro_generator import generate_starccm_java_macro
from starccm_surface_catalog import surface_catalog,validate_pairs

class CompactExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.model=BundleModel(pitch=11.64);cls.model.selected_subchannels={18,22}
        cls.mesh=build_mesh_from_bundle_model(cls.model,MeshParams(ni=45,nj=20,nz=2,z_len=.3))
    def dialog(self,parent=None):
        d=StarCcmExportDialog(parent,mesh_result=self.mesh,bundle_model=self.model,
            fluid_props=dict(density=747.339,dyn_vis=9.27e-5,cp=5225.,**{'lambda':.575},t_ref_c=290.,p_ref_mpa=16.2))
        self.addCleanup(d.deleteLater);return d
    def macro(self,d):return generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,d.read_options())
    def test_recorded_iapws_transport_choices_are_exported_independently(self):
        d=self.dialog();d.property_choice.setCurrentIndex(1)
        self.assertTrue(d.viscosity_method.model().item(1).isEnabled())
        for mu,conductivity in ((0,0),(1,0),(0,1),(1,1)):
            d.viscosity_method.setCurrentIndex(mu);d.conductivity_method.setCurrentIndex(conductivity)
            code=self.macro(d)
            self.assertEqual('setMethod(IapwsDynamicViscosityMethod.class)' in code,bool(mu))
            self.assertEqual('setMethod(IapwsThermalConductivityMethod.class)' in code,bool(conductivity))
            self.assertIn('true,true,'+str(not mu).lower()+','+str(not conductivity).lower()+');',code)
            other=self.dialog();other.apply_options(d.read_options())
            self.assertEqual(other.viscosity_method.currentIndex(),mu)
            self.assertEqual(other.conductivity_method.currentIndex(),conductivity)

    def test_recorded_velocity_seed_binding_precedes_initialization(self):
        d=self.dialog();d.initial_velocity.setCurrentIndex(d.initial_velocity.findData('seed'))
        code=self.macro(d)
        assignment='initialVelocity.getMethod(FunctionVectorProfileMethod.class).setFieldFunction(seed);'
        self.assertIn('if (!reuse) {',code)
        self.assertLess(code.index('seed.setDefinition('),code.index(assignment))
        self.assertLess(code.index(assignment),code.index('initializeFirstSolution(sim,reuse,'))
        other=self.dialog();other.apply_options(d.read_options())
        self.assertEqual(other.initial_velocity.currentData(),'seed')
        d.initial_velocity.setCurrentIndex(d.initial_velocity.findData('zero'))
        self.assertNotIn(assignment,self.macro(d))
        options=d.read_options();options['workflow'].update(initial_velocity='seed',velocity_seed=False)
        with self.assertRaisesRegex(ValueError,'VelocitySeed'):
            generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,options)

    def test_compact_iapws_visibility_and_gravity_row(self):
        d=self.dialog();d.show();d.tabs.setCurrentIndex(1);self.app.processEvents()
        self.assertTrue(d.constant_properties.isVisible());self.assertFalse(d.iapws_transport.isVisible())
        d.property_choice.setCurrentIndex(1);self.app.processEvents()
        self.assertFalse(d.constant_properties.isVisible());self.assertTrue(d.iapws_transport.isVisible())
        self.assertTrue(d.chk_thermal.isChecked());self.assertFalse(d.chk_thermal.isEnabled())
        self.assertEqual(d.chk_gravity.parentWidget(),d.combo_gravity.parentWidget())
        self.assertLessEqual(d.fluid_fields['density'].maximumWidth(),145)
        self.assertEqual(d.chk_group_objects.text(),'Папки объектов')
        d.close()
    def test_independent_unsteady_rst_and_hybrid_constraint(self):
        d=self.dialog();d.simulation_mode.setCurrentIndex(1)
        self.assertEqual(d.turbulence_choice.currentData(),'rst')
        code=self.macro(d);self.assertIn('phys.enable(ImplicitUnsteadyModel.class)',code)
        self.assertIn('phys.enable(ReynoldsStressTurbulence.class)',code)
        self.assertNotIn('phys.enable(SteadyModel.class)',code)
        other=self.dialog();other.apply_options(d.read_options());self.assertTrue(other.mean_group.isEnabled())
        d.turbulence_choice.setCurrentIndex(1);self.assertTrue(d.rb_turb_srh.isChecked())
        d.simulation_mode.setCurrentIndex(0);self.assertEqual(d.turbulence_choice.currentData(),'rst')
        self.assertFalse(d.turbulence_choice.model().item(1).isEnabled())
    def test_properties_sync_from_current_calculator_state(self):
        from types import SimpleNamespace
        parent=QWidget();self.addCleanup(parent.deleteLater)
        parent.mesh_subpanel=SimpleNamespace(current_fluid_props=dict(density=730.,dyn_vis=1e-4,cp=5000.,**{'lambda':.6}))
        d=self.dialog(parent);self.assertEqual(d.fluid_fields['density'].value(),730.)
        parent.mesh_subpanel.current_fluid_props['density']=740.;d.sync_fluid_button.click()
        self.assertEqual(d.fluid_fields['density'].value(),740.)
        parent.mesh_subpanel.last_yplus_result=dict(velocity=4.5,reynolds=1234.)
        d.sync_fluid_button.click();self.assertEqual(d.yplus_data['velocity'],4.5)
    def test_heat_rows_follow_surface_grouping_and_exclude_nonfuel(self):
        d=self.dialog();d.heat_enabled.setChecked(True)
        self.assertEqual(len(d._heat_fields),6)
        d.topology_choice.setCurrentIndex(1);d.rod_choice.setCurrentIndex(1)
        self.assertEqual(len(d._heat_fields),4)
        d.rod_choice.setCurrentIndex(2);self.assertEqual(list(d._heat_fields),['rod_s1','rod_s2'])
        for n,field in enumerate(d._heat_fields.values(),1):field.setText(str(n*12345))
        code=self.macro(d)
        self.assertIn('configureHeatInput(sim,"q1",1.2345000000000000e+04)',code)
        self.assertIn('configureHeatInput(sim,"q2",2.4690000000000000e+04)',code)
        self.assertIn('meshBuilder.HeatGroup.rod_s1',code);self.assertIn('setFieldFunction(heatQ2)',code)
        other=deepcopy(self.model);other.rods[13].rod_type='guide'
        cat=surface_catalog(self.mesh,other,'monolithic')
        self.assertTrue(any(r['kind']=='guide' for r in cat['rods']))
        self.assertTrue(all(13 not in r['rod_ids'] for r in cat['rods'] if r['kind']=='fuel'))
    def test_profiles_restore_heat_values_and_pairs(self):
        d=self.dialog();d.heat_enabled.setChecked(True)
        for n,field in enumerate(d._heat_fields.values(),1):field.setText(str(123*n))
        self.add_valid_pair(d)
        values=d.read_options()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';save_profile(values,path)
            other=self.dialog();other.apply_options(load_profile(path,2))
            self.assertEqual(other.read_options(),values)
    @staticmethod
    def add_valid_pair(d):
        sides=[r for r in d._surface_catalog['sides'] if not r['shared']]
        for a in sides:
            for b in sides:
                pair=dict(first=a['id'],second=b['id'],kind='periodic_translation')
                try:validate_pairs([pair],d._surface_catalog)
                except ValueError:continue
                d.boundary_selection_mode.setCurrentIndex(1);d.surface_condition.setCurrentIndex(d.surface_condition.findData('periodic'));d.surface_a.setCurrentIndex(d.surface_a.findData(a['id']));d.surface_b.setCurrentIndex(d.surface_b.findData(b['id']));d.add_surface_pair();return pair
        raise AssertionError('reference has no compatible periodic pair')
    def test_pair_assignment_export_and_rejections(self):
        d=self.dialog();pair=self.add_valid_pair(d);self.assertEqual(len(d._pairs),1)
        d.add_surface_pair();self.assertEqual(len(d._pairs),1)
        code=self.macro(d);self.assertIn('InterfaceConfigurationOption.Type.PERIODIC',code)
        self.assertIn(pair['first'],code);self.assertIn('SelectedInterface_1',code)
        wrong=dict(pair,second=pair['first'])
        with self.assertRaises(ValueError):validate_pairs([wrong],d._surface_catalog)
        options=d.read_options();options['workflow']['boundary_pairs']=[dict(pair,second='missing')]
        with self.assertRaises(ValueError):generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,options)
    def test_internal_interface_can_be_left_as_two_walls(self):
        d=self.dialog();self.assertEqual(len(d._internal_combos),1)
        combo=next(iter(d._internal_combos.values()));combo.setCurrentIndex(1)
        options=d.read_options();self.assertEqual(len(options['workflow']['disabled_internal_pairs']),1)
        code=self.macro(d);self.assertIn('if ((ci.subNum==1 && cj.subNum==2)',code)
        self.assertNotIn('meshMgr.combineBoundaries(new ArrayList<>(allInlets))',code)
        d.topology_choice.setCurrentIndex(1);self.assertEqual(d.read_options()['workflow']['disabled_internal_pairs'],[])
    def test_default_seed_and_bad_heat_draft(self):
        d=self.dialog();code=self.macro(d)
        for name in ('VelocitySeed','seedX','seedY','thetaZ','Apert','pi'):self.assertIn('"'+name+'"',code)
        d.heat_enabled.setChecked(True);first=next(iter(d._heat_fields.values()));first.setText('bad')
        with self.assertRaises(ValueError):d.read_options()
        d.heat_enabled.setChecked(False);self.assertFalse(d.read_options()['workflow']['heat_enabled'])
    def test_three_subchannels_have_three_subchannel_heat_groups(self):
        model=deepcopy(self.model)
        third=next(sid for sid,s in model.subchannels.items() if sid not in model.selected_subchannels and s.sub_type=='interior' and any(len(set(s.rod_ids)&set(model.subchannels[old].rod_ids))==2 for old in model.selected_subchannels))
        model.selected_subchannels.add(third)
        mesh=build_mesh_from_bundle_model(model,MeshParams(ni=20,nj=15,nz=2,z_len=.3))
        cat=surface_catalog(mesh,model,'monolithic')
        self.assertEqual(len([r for r in cat['rods'] if r['kind']=='fuel']),3)
    def test_real_preview_pick_selects_corresponding_heat_row(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        d=self.dialog();d.show();self.app.processEvents()
        key=next(iter(d._heat_fields));item=d.surface_preview.items_by_id[key][0]
        for scale in (.6,1.,1.6):
            d.surface_preview.resetTransform();d.surface_preview.fitInView(d.surface_preview.scene().itemsBoundingRect().adjusted(-1,-1,1,1),Qt.KeepAspectRatio);d.surface_preview.scale(scale,scale)
            point=d.surface_preview.mapFromScene(item.path().pointAtPercent(.5))
            self.assertEqual(d.surface_preview.itemAt(point),item)
            QTest.mouseClick(d.surface_preview.viewport(),Qt.LeftButton,pos=point);self.app.processEvents()
            self.assertEqual(d.preview_selection.text(),key)
            self.assertEqual(d.heat_table.currentRow(),0)
        d.close()
    def test_invalid_heat_draft_survives_group_switch(self):
        d=self.dialog();d.heat_enabled.setChecked(True)
        key=next(iter(d._heat_fields));d._heat_fields[key].setText('bad');d._heat_fields[key].edited.emit()
        d.rod_choice.setCurrentIndex(2);d.rod_choice.setCurrentIndex(0)
        self.assertEqual(d._heat_fields[key].text(),'bad')
        with self.assertRaises(ValueError):d.read_options()
    def test_stale_heat_group_and_disabled_internal_key_are_rejected(self):
        d=self.dialog();d.heat_enabled.setChecked(True);options=d.read_options()
        options['workflow']['heat_values']['not_a_wall']=10.
        before=d.read_options()
        with self.assertRaises(ValueError):d.apply_options(options)
        self.assertEqual(d.read_options(),before)
        with self.assertRaises(ValueError):generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,options)
        options=d.read_options();options['workflow']['disabled_internal_pairs']=['missing']
        with self.assertRaises(ValueError):generate_starccm_java_macro('mesh.xyz',self.mesh,self.model,d.read_fluid(),d.yplus_data,options)
    def test_heat_parameter_updates_execute_without_erasing_same_macro_edits(self):
        import shutil,subprocess
        from starccm_unified_support import HEAT_SUPPORT
        java=shutil.which('java') or os.environ.get('TMC_JAVA')
        if not java or 'jdk.compiler' not in subprocess.run([java,'--list-modules'],capture_output=True,text=True).stdout:self.skipTest('JDK compiler unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'CheckHeat.java';fixture=Path(__file__).parent/'fixtures'/'star_heat_harness.java'
            file.write_text(fixture.read_text().replace('// HELPERS',HEAT_SUPPORT))
            run=subprocess.run([java,str(file)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
