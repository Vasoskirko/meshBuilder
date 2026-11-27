"""Boundary selection, profile safety and generated native assignments."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from copy import deepcopy
from PySide6.QtCore import Qt,QItemSelectionModel,QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import test_compact_star_export as fixture
from starccm_surface_catalog import validate_surface_settings
from starccm_workflow import validate_workflow

class BoundaryEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.model=fixture.CompactExportTests.model;cls.mesh=fixture.CompactExportTests.mesh
    dialog=fixture.CompactExportTests.dialog
    macro=fixture.CompactExportTests.macro
    def select(self,d,first,second=None,kind='symmetry',value=1.):
        d.boundary_selection_mode.setCurrentIndex(1 if second else 0)
        d.surface_a.setCurrentIndex(d.surface_a.findData(first))
        if second:d.surface_b.setCurrentIndex(d.surface_b.findData(second))
        d.surface_condition.setCurrentIndex(d.surface_condition.findData(kind));d.boundary_flow_auto.setChecked(False);d.boundary_value.setValue(value);d.add_surface_pair()
    def test_missing_calculator_data_uses_existing_density(self):
        from starccm_export_dialog import StarCcmExportDialog
        for props in ({},{'t_ref_c':290.}):
            d=StarCcmExportDialog(fluid_props=props);self.addCleanup(d.deleteLater)
            self.assertEqual(d.reference_density.value(),d.fluid_fields['density'].model.raw)
            self.assertEqual(d._surface_catalog.get('endcaps',[]),[])

    def test_external_gap_references_compile_in_generated_lexical_scopes(self):
        import re,shutil,subprocess,tempfile
        from pathlib import Path
        java=os.environ.get('TMC_JAVA') or shutil.which('java')
        if not java:self.skipTest('JDK unavailable')
        projections=[]
        for fuse in (False,True):
            for kind in ('none','symmetry','fully_developed'):
                d=self.dialog();d.topology_choice.setCurrentIndex(int(fuse))
                if kind=='symmetry':self.select(d,'Inlet' if fuse else 'Inlet_s1',kind=kind)
                if kind=='fully_developed':self.select(d,'Inlet' if fuse else 'Inlet_s1','Outlet' if fuse else 'Outlet_s1',kind, .154)
                source=self.macro(d)
                # Preserve actual brace ancestry, remove unrelated STAR operations.
                # This is a lexical-scope compilation check, not a Siemens API stub.
                clean=re.sub(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*',lambda m:re.sub(r'[^\n]',' ',m.group()),source,flags=re.S)
                root=[];stack=[root]
                for original,line in zip(source.splitlines(),clean.splitlines()):
                    if re.search(r'\bexternalGaps\b',line):
                        statement=original.strip()
                        if 'markBoundaryRoles' in statement:statement='externalGaps.size();'
                        stack[-1].append(statement)
                    for ch in line:
                        if ch=='{':
                            child=[];stack[-1].append(child);stack.append(child)
                        elif ch=='}':stack.pop()
                def render(items):
                    result=[]
                    for item in items:
                        if isinstance(item,str):result.append(item)
                        else:
                            nested=render(item)
                            if nested:result.append('{\n'+nested+'\n}')
                    return '\n'.join(result)
                projections.append('{\n'+render(root)+'\n}')
        source='import java.util.*; class GapScopeCheck { static class Boundary {} static class GapCandidate { boolean paired; Boundary bnd; } static List<GapCandidate> gapCandidates=new ArrayList<>(); public static void main(String[] args) {\n'+'\n'.join(projections)+'\n} }'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'GapScopeCheck.java';path.write_text(source)
            result=subprocess.run([java,str(path)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_reference_fields_visibility_and_native_definitions(self):
        d=self.dialog();d.show();d.tabs.setCurrentIndex(1);self.app.processEvents()
        self.assertFalse(d.reference_density_row.isVisible())
        d.chk_gravity.setChecked(True);self.assertTrue(d.reference_density_row.isVisible())
        d.reference_density_auto.setChecked(False);d.reference_density.setText('700,25');d.minimum_wall_distance.setText('2.5e-8')
        code=self.macro(d)
        self.assertIn('get(ReferenceDensity.class).setDefinition("${ReferenceDensity}")',code)
        self.assertIn('700.25',code);self.assertIn('get(MinimumAllowableWallDistance.class)',code)
        self.assertIn('2.5e-08',code)
        other=self.dialog();other.apply_options(d.read_options())
        self.assertEqual(other.reference_density.value(),700.25);self.assertEqual(other.minimum_wall_distance.value(),2.5e-8)
        other.reference_density_auto.setChecked(True);self.assertEqual(other.reference_density.value(),other.fluid_fields['density'].value())
        d.chk_gravity.setChecked(False);self.assertNotIn('get(ReferenceDensity.class)',self.macro(d))
        d.minimum_wall_distance.setText('0')
        with self.assertRaises(ValueError):d.read_options()
        d.close()
    def test_tree_endcaps_follow_fuse_and_select_pair(self):
        d=self.dialog();caps=d._surface_catalog['endcaps'];self.assertEqual(len(caps),4)
        self.assertEqual(len(d._surface_tree_items),len(caps)+len(d._surface_catalog['rods'])+len(d._surface_catalog['sides']))
        tree=d.surface_tree
        tree.setCurrentItem(d._surface_tree_items['Inlet_s1'],0,QItemSelectionModel.ClearAndSelect)
        self.assertEqual(d.surface_a.currentData(),'Inlet_s1')
        d._surface_tree_items['Outlet_s1'].setSelected(True)
        self.assertEqual(d.boundary_selection_mode.currentData(),'pair')
        self.assertEqual({d.surface_a.currentData(),d.surface_b.currentData()},{'Inlet_s1','Outlet_s1'})
        area=sum(c['area'] for c in caps if c['role']=='Inlet')
        d.topology_choice.setCurrentIndex(1)
        self.assertEqual({c['id'] for c in d._surface_catalog['endcaps']},{'Inlet','Outlet'})
        self.assertAlmostEqual(d._surface_catalog['endcaps'][0]['area'],area,14)
    def test_fully_developed_mass_flow_and_default_periodic(self):
        for fuse in (False,True):
            d=self.dialog();d.topology_choice.setCurrentIndex(int(fuse))
            a,b=('Inlet','Outlet') if fuse else ('Inlet_s1','Outlet_s1')
            self.select(d,a,b,'fully_developed',.154)
            self.assertEqual(len(d._pairs),1,d.surface_status.text())
            code=self.macro(d)
            self.assertIn('setInterfaceType((FullyDevelopedInterface)',code)
            self.assertIn('FullyDevelopedFlowOption.Type.MASS_FLOW_RATE',code)
            self.assertIn('get(FullyDevelopedMassFlowRate.class)',code)
            self.assertIn('${PeriodicMassFlow_1}',code)
            self.assertLess(code.index('physicalValuesConfigured = configurePhysicalValues'),code.index('setInterfaceType((FullyDevelopedInterface)'))
            self.assertLess(code.index('get(FullyDevelopedMassFlowRate.class)'),code.index('initializeFirstSolution(sim,reuse,'))
            self.select(d,a,b,'fully_developed',.2);self.assertEqual(len(d._pairs),1);self.assertEqual(d._pairs[0]['mass_flow'],.2)
            other=self.dialog();other.apply_options(d.read_options());self.assertEqual(other._pairs,d._pairs)
        d=self.dialog();self.select(d,'Inlet_s1','Outlet_s1','periodic')
        code=self.macro(d);self.assertIn('InterfaceConfigurationOption.Type.PERIODIC',code)
        self.assertNotIn('setInterfaceType((FullyDevelopedInterface)',code)
        self.assertNotIn('RotationalPeriodicTransform',code)
    def test_single_conditions_and_conflicts(self):
        d=self.dialog();self.select(d,'Inlet_s1',kind='mass_flow_inlet',value=.154)
        self.select(d,'Outlet_s1',kind='pressure_outlet',value=100.)
        side=next(r['id'] for r in d._surface_catalog['sides'] if not r['shared'])
        self.select(d,side,kind='symmetry')
        code=self.macro(d)
        for name in ('MassFlowBoundary','PressureBoundary','SymmetryBoundary','MassFlowRateProfile','StaticPressureProfile'):
            self.assertIn(name+'.class',code)
        other=self.dialog();other.apply_options(d.read_options());self.assertEqual(other._conditions,d._conditions)
        self.select(d,'Inlet_s1','Outlet_s1','fully_developed',.154)
        self.assertEqual(d._pairs,[]);self.assertIn('пару',d.surface_status.text())
        self.select(d,'Outlet_s1',kind='wall');self.assertEqual(len(d._conditions),3)
        self.assertEqual(next(r for r in d._conditions if r['surface']=='Outlet_s1')['kind'],'wall')
    def test_shared_surface_pair_overrides_automatic_stitching(self):
        d=self.dialog();shared=[r for r in d._surface_catalog['sides'] if r['shared']]
        self.select(d,shared[0]['id'],shared[1]['id'],'internal')
        self.assertEqual(len(d._pairs),1,d.surface_status.text())
        code=self.macro(d)
        self.assertIn('if(ci.subNum==',code);self.assertIn('if(cj.subNum==',code)
        self.assertIn('SelectedInterface_1',code)
        self.assertNotIn('selectedPair1.getTopology().setSelected',code)
        other=self.dialog();other.topology_choice.setCurrentIndex(1)
        self.assertTrue(all(r['id'] not in other._surface_tree_items for r in shared))

    def test_invalid_and_stale_settings_refused_before_mutating_dialog(self):
        d=self.dialog();original=d.read_options();bad=deepcopy(original)
        bad['workflow']['boundary_conditions']=[dict(surface='missing',kind='symmetry',value=0.)]
        with self.assertRaises(ValueError):d.apply_options(bad)
        self.assertEqual(d.read_options(),original)
        for invalid in (dict(reference_density=-1.),dict(minimum_wall_distance=0.),dict(boundary_pairs=[dict(first='Inlet_s1',second='Outlet_s1',kind='fully_developed',mass_flow=0.)])):
            with self.assertRaises(ValueError):validate_workflow(invalid)
        self.select(d,'Inlet_s1','Outlet_s2','fully_developed',1.)
        self.assertEqual(d._pairs,[])
        self.select(d,'Inlet_s1','Outlet_s1','internal')
        self.assertEqual(d._pairs,[])
    def test_preview_endcap_click_has_no_qt_selection_rectangle(self):
        from PySide6.QtWidgets import QGraphicsItem
        d=self.dialog();d.show();self.app.processEvents()
        d.preview_view.setCurrentIndex(d.preview_view.findData('Inlet'));self.app.processEvents()
        item=d.surface_preview.items_by_id['Inlet_s1'][0]
        self.assertFalse(item.flags()&QGraphicsItem.ItemIsSelectable)
        bounds=item.path().boundingRect()
        # Find a point inside fluid rather than the excluded rod circles.
        point=next(bounds.topLeft()+QPointF(bounds.width()*i/20,bounds.height()*j/20) for i in range(1,20) for j in range(1,20) if item.path().contains(bounds.topLeft()+QPointF(bounds.width()*i/20,bounds.height()*j/20)))
        QTest.mouseClick(d.surface_preview.viewport(),Qt.LeftButton,Qt.NoModifier,d.surface_preview.mapFromScene(point));self.app.processEvents()
        self.assertEqual(d.surface_a.currentData(),'Inlet_s1');self.assertFalse(d.surface_preview.scene().selectedItems())
        d.preview_view.setCurrentIndex(d.preview_view.findData('Outlet'));self.app.processEvents()
        item=d.surface_preview.items_by_id['Outlet_s1'][0];shift=item.path().boundingRect().topLeft()-bounds.topLeft()
        QTest.mouseClick(d.surface_preview.viewport(),Qt.LeftButton,Qt.ControlModifier,d.surface_preview.mapFromScene(point+shift));self.app.processEvents()
        self.assertEqual(d.boundary_selection_mode.currentData(),'pair');self.assertEqual(len(d.surface_tree.selectedItems()),2)
        d.close()
