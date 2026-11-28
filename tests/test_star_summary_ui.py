"""Review cards reflect current controls without changing export options."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
import test_compact_star_export as fixture
from test_unified_tdc import enable_tdc

class SummaryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def test_review_preserves_options_and_navigation(self):
        d=self.dialog();before=d.read_options();d.show();d.tabs.setCurrentIndex(7);self.app.processEvents()
        self.assertEqual(d.read_options(),before);self.assertEqual(len(d.summary_cards),7)
        self.assertFalse(d.summary_text.isVisible());self.assertFalse(d.chk_initialize.isVisible())
        self.assertTrue(d.summary_tab.isAncestorOf(d.chk_initialize));self.assertIn('не создаются',d.summary_cards['quality'].text())
        self.assertNotIn('TDC_Hybrid.java',d.summary_files.text())
        d.summary_details_toggle.setChecked(True);self.assertTrue(d.summary_text.isVisible())
        d.summary_edit_buttons['physics'].click();self.assertEqual(d.tabs.currentIndex(),1)
        d.rb_turb_srh.setChecked(True);d.tabs.setCurrentIndex(7);self.assertIn('Δt',d.summary_cards['time'].text())
        self.assertIn('Одно общее окно',d.summary_cards['time'].text())
    def test_tdc_bundle_and_error_are_distinct_from_mesh_acceptance(self):
        d=enable_tdc(self.dialog());before=d.read_options();d.tabs.setCurrentIndex(7)
        self.assertIn('TDC_Hybrid.java',d.summary_files.text());self.assertIn('Initialize вручную',d.summary_steps.text())
        self.assertIn('обязательно',d.summary_cards['parts'].text());self.assertEqual(d.read_options(),before)
        self.assertIn('проверка сетки',d.summary_status.text())
        d._pairs=[];d._summary_refresh();self.assertIn('Требует внимания',d.summary_status.text())
        self.assertNotIn('Настройки проверены',d.summary_status.text())
        before['workflow']['tdc_settings'].update(a=2,b=1);d.apply_options(before)
        self.assertIn('A = Подканал 2',d.summary_cards['tdc'].text())
        self.assertNotIn('Требует внимания',d.summary_status.text())
