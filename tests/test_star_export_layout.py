"""Exercise layout under the actual builder theme, rather than bare dialogs only."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QWidget,QGroupBox
from bundle_styles import SCIENTIFIC_QSS
import test_compact_star_export as fixture

class ExportLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CompactExportTests.setUpClass();cls.app=fixture.CompactExportTests.app;cls.mesh=fixture.CompactExportTests.mesh;cls.model=fixture.CompactExportTests.model
    dialog=fixture.CompactExportTests.dialog
    def test_builder_theme_does_not_stretch_help_rows_or_clip_short_lists(self):
        for extra in ('','\nQWidget {font-size:18px;}'):
            with self.subTest(extra=extra):
                parent=QWidget();parent.setStyleSheet(SCIENTIFIC_QSS+extra);self.addCleanup(parent.deleteLater)
                d=self.dialog(parent);d.tabs.setCurrentIndex(2);d.show();self.app.processEvents()
                page=d.tabs.widget(2).widget()
                groups=[w for w in page.findChildren(QGroupBox) if w.isVisible()]
                for height in (850,1250):
                    d.resize(1100,height);self.app.processEvents()
                    for group in groups:
                        self.assertLessEqual(group.height(),group.sizeHint().height()+2)
                        for w in group.findChildren(QWidget):
                            if type(w) is QWidget and w.isVisible() and w.layout() is not None:
                                self.assertLessEqual(w.height(),w.sizeHint().height()+2)
                    for listing in (d.parts_targets,d.gap_list):
                        last=listing.visualItemRect(listing.item(listing.count()-1))
                        self.assertLessEqual(last.bottom(),listing.viewport().height())
                d.close()
