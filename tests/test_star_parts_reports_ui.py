"""Single preview, calculated periodic flow and independent geometry/report scopes."""
import os,re,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
from unittest.mock import patch
from PySide6.QtCore import Qt
import test_compact_star_export as fixture
from starccm_flow_defaults import calculator_mass_flow

class PartsReportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.model=fixture.CompactExportTests.model;cls.mesh=fixture.CompactExportTests.mesh
    dialog=fixture.CompactExportTests.dialog
    macro=fixture.CompactExportTests.macro
    def targets(self,d,ids):
        for i in range(d.parts_targets.count()):
            item=d.parts_targets.item(i);item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in ids else Qt.Unchecked)
    def no_reports(self,d):
        d.chk_reports.setChecked(False)
        for cb in d.report_checkboxes.values():cb.setChecked(False)
        for i in range(d.report_targets.count()):d.report_targets.item(i).setCheckState(Qt.Unchecked)
    def test_single_model_switches_endcap_view_without_copying_model(self):
        d=self.dialog();d.preview_view.setCurrentIndex(d.preview_view.findData('Inlet'))
        self.assertIn('Inlet_s1',d.surface_preview.items_by_id)
        self.assertNotIn('Outlet_s1',d.surface_preview.items_by_id)
        self.assertFalse(any(k.startswith('rod_') for k in d.surface_preview.items_by_id))
        inlet_bounds=d.surface_preview.scene().itemsBoundingRect()
        d.preview_view.setCurrentIndex(d.preview_view.findData('Outlet'))
        self.assertNotIn('Inlet_s1',d.surface_preview.items_by_id);self.assertIn('Outlet_s1',d.surface_preview.items_by_id)
        self.assertEqual(inlet_bounds,d.surface_preview.scene().itemsBoundingRect())
        d.surface_preview.highlight('Inlet_s1');self.assertEqual(d.preview_view.currentData(),'Inlet')
        d.preview_view.setCurrentIndex(0);self.assertTrue(any(k.startswith('rod_') for k in d.surface_preview.items_by_id))
    def test_calculator_default_uses_reynolds_geometry_and_updates_auto_pair(self):
        d=self.dialog();d.boundary_selection_mode.setCurrentIndex(1)
        d.surface_a.setCurrentIndex(d.surface_a.findData('Inlet_s1'));d.surface_b.setCurrentIndex(d.surface_b.findData('Outlet_s1'))
        d.surface_condition.setCurrentIndex(d.surface_condition.findData('fully_developed'))
        expected=calculator_mass_flow(d._surface_catalog,d.read_fluid(),d.yplus_data,'Inlet_s1')
        self.assertAlmostEqual(d.boundary_value.value(),expected);self.assertFalse(d.boundary_value.isEnabled())
        d.add_surface_pair();self.assertTrue(d._pairs[0]['mass_flow_auto'])
        d.yplus_data['reynolds']*=2
        values=d.read_options();self.assertAlmostEqual(values['workflow']['boundary_pairs'][0]['mass_flow'],expected*2)
        d.surface_tree.clearSelection();d._surface_tree_items['Inlet_s1'].setSelected(True);d._surface_tree_items['Outlet_s1'].setSelected(True)
        self.assertAlmostEqual(d.boundary_value.value(),expected*2)
        code=self.macro(d);self.assertIn(f'{expected*2:.16e}',code)
        other=self.dialog();other.apply_options(values);self.assertTrue(other._pairs[0]['mass_flow_auto'])
        d.topology_choice.setCurrentIndex(1)
        fused=calculator_mass_flow(d._surface_catalog,d.read_fluid(),d.yplus_data,'Inlet')
        self.assertAlmostEqual(fused,expected*4,10)
    def test_manual_periodic_flow_remains_manual(self):
        d=self.dialog();d.boundary_selection_mode.setCurrentIndex(1)
        d.surface_a.setCurrentIndex(d.surface_a.findData('Inlet_s1'));d.surface_b.setCurrentIndex(d.surface_b.findData('Outlet_s1'))
        d.surface_condition.setCurrentIndex(d.surface_condition.findData('fully_developed'));d.boundary_flow_auto.setChecked(False);d.boundary_value.setText('0,25');d.add_surface_pair()
        d.yplus_data['reynolds']*=2;self.assertEqual(d.read_options()['workflow']['boundary_pairs'][0]['mass_flow'],.25)
    def test_energy_gates_heat_but_retains_values_for_reenable(self):
        d=self.dialog();d.heat_enabled.setChecked(True);d._heat_fields[next(iter(d._heat_fields))].setText('12345')
        d.chk_thermal.setChecked(False);self.assertFalse(d.heat_enabled.isEnabled());self.assertFalse(d.heat_table.isEnabled())
        self.assertFalse(d.read_options()['workflow']['heat_enabled']);self.assertIn('Нагрев ТВЭЛ: не назначается',d.summary_text.toPlainText())
        d.topology_choice.setCurrentIndex(1);self.assertFalse(d.heat_table.isEnabled())
        d.chk_thermal.setChecked(True);self.assertTrue(d.heat_enabled.isEnabled());self.assertTrue(d.read_options()['workflow']['heat_enabled'])
        self.assertIn(12345.,d.read_options()['workflow']['heat_values'].values())
    def test_derived_parts_exact_planes_and_report_scope_are_independent(self):
        d=self.dialog();self.no_reports(d);d.chk_gap_sections.setChecked(False);d.chk_axis_probes.setChecked(False)
        self.targets(d,{0,1});d.plane_scheme.setCurrentIndex(d.plane_scheme.findData('uniform'));d.plane_count.setValue(4)
        code=self.macro(d)
        names=re.findall(r'createPlaneSection\(sim, labCoord, uLen, [^\n]*?"([^"]+)", lz \*',code)
        self.assertEqual(len([n for n in names if n.startswith('Section_Global')]),4)
        self.assertEqual(len([n for n in names if n.startswith('Subchannel_1_Section')]),4)
        self.assertFalse(any(n.startswith('Subchannel_2_Section') for n in names))
        d.report_checkboxes['hydraulics'].setChecked(True);d.report_targets.item(1).setCheckState(Qt.Checked)
        code=self.macro(d);self.assertIn('createSubchannelAnalysis(sim,2,',code);self.assertNotIn('createSubchannelAnalysis(sim,1,',code)
        values=d.read_options();self.assertEqual(values['selected_subchannels'],[1]);self.assertEqual(values['workflow']['report_subchannels'],[2])
        other=self.dialog();other.apply_options(values);self.assertEqual(other.read_options(),values)
    def test_plane_presets_produce_only_requested_parts(self):
        d=self.dialog();self.no_reports(d);d.chk_gap_sections.setChecked(False);d.chk_axis_probes.setChecked(False);self.targets(d,{0,1})
        for scheme,count in (('ends',2),('three',3),('none',0)):
            d.plane_scheme.setCurrentIndex(d.plane_scheme.findData(scheme));code=self.macro(d)
            names=re.findall(r'createPlaneSection\(sim, labCoord, uLen, [^\n]*?"([^"]+)", lz \*',code)
            self.assertEqual(len(names),count*2)
        original=d.read_options();bad=deepcopy(original);bad['workflow']['report_subchannels']=[3]
        with self.assertRaises(ValueError):d.apply_options(bad)
        self.assertEqual(d.read_options(),original)

    def test_tabs_help_and_review_destination(self):
        d=self.dialog();self.assertEqual(d.tabs.count(),8)
        self.assertEqual(d.tabs.tabText(2),'3. Производные части');self.assertEqual(d.tabs.tabText(3),'4. Отчёты (Репорты)')
        self.assertTrue(d.tabs.widget(3).isAncestorOf(d.chk_reports))
        self.assertTrue(all(d.tabs.widget(3).isAncestorOf(w) for w in d.report_checkboxes.values()))
        d.show();d.tabs.setCurrentIndex(2);self.app.processEvents();self.assertFalse(d.gap_table.isVisible());self.assertTrue(d.gap_list.isVisible())
        self.assertEqual(d.parts_targets.item(0).text(),'Вся модель')
        with patch.object(d,'generate_and_save') as export:
            d.generate_button.click();self.assertEqual(d.tabs.currentIndex(),7);export.assert_not_called()
            d.generate_button.click();export.assert_called_once()
        d.close()
    def test_legacy_profile_keeps_original_plane_counts(self):
        d=self.dialog();values=d.read_options();values['workflow'].pop('plane_scheme');values['workflow'].pop('report_subchannels')
        values.update(n_planes=4,n_sub_planes=0,sub_planes=True,selected_subchannels=[2])
        d.apply_options(values);result=d.read_options();self.assertEqual(result['n_planes'],4);self.assertEqual(result['n_sub_planes'],0)
        self.assertEqual(result['workflow']['plane_scheme'],'legacy');self.assertEqual(result['workflow']['report_subchannels'],[2])
