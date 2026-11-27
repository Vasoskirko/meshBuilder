"""Show one exchange per row without merging its signed per-side settings."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt
from test_tdc_paths import fixture,enable_tdc,lateral

class ConnectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def test_readable_overview_maps_swapped_roles_and_preserves_profile(self):
        d=enable_tdc(self.dialog());lateral(d);d.tdc_a.setCurrentIndex(1);d.tdc_b.setCurrentIndex(0)
        before=d.read_options();d.show();d.tabs.setCurrentIndex(6);self.app.processEvents()
        t=d.tdc_connections;self.assertEqual(t.rowCount(),3)
        self.assertEqual(t.item(0,0).text(),'Целевой зазор');self.assertEqual(len(t.item(0,0).data(Qt.UserRole)),2)
        self.assertIn('A = Подканал 2; B = Подканал 1',d.tdc_mapping.text())
        self.assertEqual(t.item(1,2).text(),'Internal + Periodic');self.assertIn('не соединены',t.item(2,0).text())
        self.assertFalse(d.tdc_details_panel.isVisible());d.tdc_details_toggle.setChecked(True);self.app.processEvents()
        self.assertTrue(d.tdc_paths_table.isVisible());self.assertEqual(d.tdc_paths_table.rowCount(),6)
        t.selectRow(1);self.assertIn('Side_s',d.tdc_connection_details.text())
        self.assertEqual(d.read_options(),before)
        other=self.dialog();other.apply_options(before);self.assertEqual(other.read_options(),before)
    def test_distinct_signed_report_names_survive_summary_refresh(self):
        d=enable_tdc(self.dialog());lateral(d)
        names={}
        for i,p in enumerate(d._tdc_rows):
            if p['kind']=='periodic':
                c=d.tdc_paths_table.cellWidget(i,3);c.setCurrentIndex(c.findData('report'))
                name='Power_'+str(p['source']);d.tdc_paths_table.cellWidget(i,4).setText(name);names[p['id']]=name
        before=d.read_options();d._tdc_refresh();self.assertEqual(d.read_options(),before)
        self.assertEqual(before['workflow']['tdc_settings']['path_reports'],names)
        self.assertIn('Отчёты мощности',d.tdc_connections.item(1,3).text())
