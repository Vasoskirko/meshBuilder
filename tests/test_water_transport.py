"""IAPWS release checkpoints and the water -> y+ -> macro data path."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import math, re, sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fluid_properties import water_iapws97,_saturation_pressure_mpa
from iapws._iapws import _Viscosity,_ThCond

class WaterTransportTests(unittest.TestCase):
    def test_r12_08_table4_viscosity_checkpoints(self):
        # Official R12-08 Table 4: T[K], rho[kg/m3], mu[microPa s].
        # https://iapws.org/technical-guidance/release/viscosity.download
        for T,rho,mu in [(298.15,998,889.735100),(298.15,1200,1437.649467),
                         (373.15,1000,307.883622),(433.15,1000,217.685358)]:
            with self.subTest(T=T,rho=rho):
                self.assertAlmostEqual(_Viscosity(rho,T)*1e6,mu,delta=5.1e-7)
    def test_r15_11_table4_conductivity_checkpoints(self):
        # Official R15-11 Table 4, no enhancement at these states. Values mW/(m K).
        # https://iapws.org/technical-guidance/release/ThCond.download
        for T,rho,k in [(298.15,0,18.4341883),(298.15,998,607.712868),
                        (298.15,1200,799.038144),(873.15,0,79.1034659)]:
            with self.subTest(T=T,rho=rho):
                self.assertAlmostEqual(_ThCond(rho,T)*1000,k,delta=5.1e-7)
    def test_public_tp_values_and_si_consistency_are_not_rounded(self):
        # Frozen IF97 + R12-08/R15-11 industrial reference states, iapws 1.5.5.
        for t,p,rho,mu,k in [(25,.1,997.047435408096,8.900225512925696e-4,.6065158268827919),
                            (300,15,725.553275227173,8.834775720679453e-5,.5632092396757247),
                            (350,100,762.3345577040078,9.591501852295469e-5,.608499831337308)]:
            with self.subTest(t=t,p=p):
                r=water_iapws97(t,p,conductivity_model="full")
                self.assertAlmostEqual(r['density'],rho,delta=2e-9)
                self.assertAlmostEqual(r['dyn_vis'],mu,delta=1e-14)
                self.assertAlmostEqual(r['lambda'],k,delta=1e-11)
                self.assertEqual(r['kin_vis'],r['dyn_vis']/r['density'])
                self.assertEqual(r['prandtl'],r['dyn_vis']*r['cp']/r['lambda'])
                self.assertEqual((r['t_ref_c'],r['p_ref_mpa']),(t,p))
                for name in ('density','dyn_vis','cp','lambda','prandtl'):self.assertIs(type(r[name]),float)
    def test_saturation_liquid_and_no_silent_vapor_or_supercritical_extension(self):
        for T in (273.15,373.15,573.15,623.15):
            ps=_saturation_pressure_mpa(T)
            r=water_iapws97(T-273.15,ps)
            self.assertGreater(r['density'],500)
            # Even an infinitesimal pressure below the public limit is rejected.
            with self.assertRaises(ValueError):water_iapws97(T-273.15,math.nextafter(ps,0))
        for t,p in [(374,25),(100,.05),(350,16),(25,101)]:
            with self.assertRaises(ValueError):water_iapws97(t,p)
    def test_operating_range_grid_has_finite_positive_transport(self):
        for t in (0,25,100,200,300,350):
            ps=_saturation_pressure_mpa(t+273.15)
            for p in (ps,ps+1e-6,max(20,ps),100):
                with self.subTest(t=t,p=p):
                    r=water_iapws97(t,p)
                    for key in ('dyn_vis','lambda','kin_vis','prandtl','cp'):
                        self.assertTrue(math.isfinite(r[key]));self.assertGreater(r[key],0)
    def test_offscreen_yplus_uses_full_properties_and_export_receives_them(self):
        from PySide6.QtWidgets import QApplication
        from yplus_dialog import YPlusDialog
        from yplus_calculator import calculate_yplus_and_step
        from mesh_core import MeshParams,generate_mesh
        from starccm_macro_generator import generate_starccm_java_macro
        app=QApplication.instance() or QApplication([])
        dialog=YPlusDialog(d_hyd_mm=10,a_fluid_mm2=40,state_dict={'temp_c':'300','press_mpa':'15'})
        self.addCleanup(dialog.deleteLater)
        dialog.rad_vel.setChecked(True);dialog.edit_vel.setText('5.62');dialog.recalc()
        self.assertTrue(dialog.btn_apply.isEnabled(),dialog.lbl_step_res.text())
        props=water_iapws97(300,15)
        self.assertEqual(dialog.current_fluid_props,props)
        expected=calculate_yplus_and_step('velocity',5.62,props['density'],props['dyn_vis'],10,40,
            y_plus=float(dialog.edit_yplus.text()))
        self.assertAlmostEqual(dialog.last_yplus_result['delta_y1_um'],expected['delta_y1_um'],places=12)
        self.assertIn('IAPWS 2011',dialog.properties_dialog.source_label.text())
        mesh=generate_mesh(MeshParams(ni=8,nj=20,nz=1))
        macro=generate_starccm_java_macro('water.xyz',mesh,None,dialog.current_fluid_props,dialog.last_yplus_result,{})
        # Existing versions format exported numbers differently, so check numeric values.
        for name,value,rtol in [('dynvis',props['dyn_vis'],1e-6),('lambda',props['lambda'],1e-3),
                                ('rho',props['density'],1e-6),('T_ref',573.15,1e-8),('P_ref',15e6,1e-8)]:
            match=re.search(r'"'+name+r'",\s*([\d.eE+-]+),',macro)
            self.assertIsNotNone(match,name)
            self.assertTrue(math.isclose(float(match.group(1)),value,rel_tol=rtol),(name,match.group(1),value))

    def test_star_reported_point_background_and_full_modes_are_explicit(self):
        r=water_iapws97(300,15)
        self.assertEqual(r['conductivity_model'],'background')
        self.assertAlmostEqual(r['lambda'],.557436764298241,delta=1e-12)
        self.assertEqual(f"{r['lambda']:.3e}",'5.574e-01')
        self.assertEqual(f"{r['dyn_vis']:.3e}",'8.835e-05')
        self.assertEqual(f"{r['density']:.3f}",'725.553')
        self.assertEqual(f"{r['cp']:.3f}",'5476.017')
        full=water_iapws97(300,15,conductivity_model='full')
        for key in ('density','dyn_vis','cp','kin_vis'):self.assertEqual(r[key],full[key])
        self.assertAlmostEqual(full['lambda'],.5632092396757247,delta=1e-12)
        self.assertNotEqual(r['prandtl'],full['prandtl'])
        self.assertEqual(r['prandtl'],r['dyn_vis']*r['cp']/r['lambda'])
        with self.assertRaises(ValueError):water_iapws97(300,15,conductivity_model='unknown')
    def test_gui_conductivity_choice_persists_and_export_uses_selected_value(self):
        from PySide6.QtWidgets import QApplication
        from yplus_dialog import YPlusDialog
        from mesh_core import MeshParams,generate_mesh
        from starccm_macro_generator import generate_starccm_java_macro
        app=QApplication.instance() or QApplication([])
        state={'temp_c':'300','press_mpa':'15'}
        d=YPlusDialog(state_dict=state);self.addCleanup(d.deleteLater)
        self.assertEqual(d.current_fluid_props['conductivity_model'],'background')
        d.combo_water_conductivity.setCurrentIndex(d.combo_water_conductivity.findData('full'))
        self.assertEqual(state['conductivity_model'],'full')
        restored=YPlusDialog(state_dict=state);self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.combo_water_conductivity.currentData(),'full')
        mesh=generate_mesh(MeshParams(ni=8,nj=20,nz=1))
        for key in ('full','background'):
            restored.combo_water_conductivity.setCurrentIndex(restored.combo_water_conductivity.findData(key))
            props=restored.current_fluid_props
            self.assertAlmostEqual(props['lambda'],water_iapws97(300,15,conductivity_model=key)['lambda'],places=12)
            code=generate_starccm_java_macro('water.xyz',mesh,None,props,restored.last_yplus_result,{})
            value=float(re.search(r'"lambda",\s*([\d.eE+-]+),',code).group(1))
            self.assertTrue(math.isclose(value,props['lambda'],rel_tol=1e-3))

    def test_second_star_state_without_changing_transport_formula(self):
        # User scalar-scene values, 290 C and 16.2 MPa. Conductivity differs
        # by 7.57e-6 W/(m K); this is recorded, not fitted away or called exact.
        r=water_iapws97(290,16.2,conductivity_model='background')
        self.assertAlmostEqual(r['density'],747.339,delta=.0005)
        self.assertAlmostEqual(r['dyn_vis'],9.27175e-5,delta=5e-11)
        self.assertAlmostEqual(r['cp'],5225.098,delta=.0005)
        self.assertAlmostEqual(r['lambda'],.5753275671409854,delta=1e-12)
        self.assertLess(abs(r['lambda']-.57532),1e-5)
        self.assertGreater(abs(r['lambda']-.57532),5e-6)
        full=water_iapws97(290,16.2,conductivity_model='full')
        self.assertAlmostEqual(full['lambda'],.5801910046304146,delta=1e-12)
