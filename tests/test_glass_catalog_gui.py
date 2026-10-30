import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QMessageBox, QTableWidget, QLineEdit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import glass_catalog as gc
from glass_catalog_ui import GlassCatalogWindow
from codev_catalog_bundle import verify
from catalog_fixtures import write_codev_tables


class ManualExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])
        cls.qt_app.setStyle("windows11")
        for name in ("msyh.ttc", "msyhl.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + name)
        cls.qt_app.setFont(QFont("Microsoft YaHei UI", 10))
        cls.qt_app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.codev, self.zemax = self.work / "CODEV", self.work / "Glasscat"
        write_codev_tables(self.codev)
        self.app = GlassCatalogWindow(settings={"codev_root": str(self.codev), "zemax_glasscat": str(self.zemax)}, persist_settings=False)
        self.source = self.work / "SOURCE.AGF"
        self.source.write_text("NM TEST 2 0 1.5168 64.17 0 0\n"
                               "CD 1.03961212 .00600069867 .231792344 .0200179144 1.01046945 103.560653\n"
                               "LD .29 2.5\nIT .55 .99 1\nIT .56 1.00005050 1\nIT .79 1.00009092 1\n")
        self.app.catalogs = [gc.load_catalog(self.source)]
        self.app.catalog_name.setText("CUSTOM")
        self.app.apply_filters()

    def tearDown(self):
        self.app.close()
        self.app.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def assert_success(self):
        self.assertIsNotNone(self.app.last_notice)
        self.assertEqual(self.app.last_notice["level"], "success", self.app.last_notice)

    def export_to(self, output, selected=False):
        with patch("glass_catalog_ui.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            self.app.export(selected)
        self.assert_success()

    def test_small_window_keeps_actions_visible_with_filters_and_notice(self):
        self.app.resize(1000, 650)
        self.app.show()
        for expanded in (False, True):
            self.app.filter_button.setChecked(expanded)
            for page in ("browse", "settings", "zemax"):
                with self.subTest(page=page, expanded=expanded):
                    self.app.nav_buttons[page].click()
                    self.app.notify("已完成操作", "详情可展开，默认不占用材料列表空间。")
                    self.qt_app.processEvents()
                    widgets = [self.app.uninstall_button, self.app.nav_buttons["zemax"]]
                    widgets += ([self.app.zemax_uninstall_button] if page == "zemax" else
                                [self.app.install_button, self.app.export_button, self.app.export_selection_button])
                    for widget in widgets:
                        self.assertTrue(widget.isVisible())
                        bounds = QRect(widget.mapTo(self.app, QPoint()), widget.size())
                        self.assertTrue(self.app.rect().contains(bounds), (widget.text(), bounds))
                    if page == "browse":
                        self.assertGreater(self.app.table.viewport().height(), 40)

    def test_page_switch_and_format_change_retain_selection(self):
        self.app.table.selectRow(0)
        for fmt, target in (("agf", "Zemax"), ("xml", "CODE V")):
            self.app.nav_buttons["settings"].click()
            self.app.format_buttons[fmt].click()
            self.app.nav_buttons["browse"].click()
            self.assertEqual([g.name for g in self.app.selected_glasses()], ["TEST"])
            self.assertIn(target, self.app.install_button.text())
            self.assertIn(fmt.upper(), self.app.export_button.text())
        self.app.set_output_format("agf")
        self.app.thickness.setText("25")
        self.export_to(self.work / "SELECTED.AGF", True)
        self.assertEqual([g.name for g in gc.load_catalog(self.work / "SELECTED.AGF").glasses], ["TEST"])

    def test_import_filter_reset_and_clear(self):
        second = self.work / "SECOND.AGF"
        second.write_text(self.source.read_text().replace("NM TEST ", "NM SECOND "))
        with patch("glass_catalog_ui.QFileDialog.getOpenFileNames", return_value=([str(self.source), str(second)], "")):
            self.app.add_files()
        self.assertEqual(len(self.app.catalogs), 2)
        self.app.values["name"].setText("SECOND")
        self.app.values["nd_min"].setText("1.5")
        self.app.values["nd_max"].setText("1.6")
        self.assertTrue(self.app.apply_filters())
        self.assertEqual([g.name for g in self.app.filtered], ["SECOND"])
        self.app.reset_filters()
        self.assertEqual(self.app.table.rowCount(), 2)
        self.app.clear()
        self.assertEqual(self.app.catalogs, [])
        self.assertEqual(self.app.table.rowCount(), 0)
        self.assertIs(self.app.table_stack.currentWidget(), self.app.empty_state)

    def test_default_export_and_bundle_install_have_no_alerts(self):
        output = self.work / "CUSTOM.xml"
        original = {p.name: p.read_bytes() for p in (self.codev / "macro").iterdir()}
        with patch.object(QMessageBox, "information", side_effect=AssertionError("modal alert")), \
             patch.object(QMessageBox, "critical", side_effect=AssertionError("modal alert")), \
             patch.object(QApplication, "beep", side_effect=AssertionError("sound")):
            self.export_to(output)
            report = json.loads(output.with_suffix(".xml.report.json").read_text(encoding="utf-8"))
            package = Path(report["codev_bundle"])
            for relative in ("glass/CUSTOM.xml", "macro/custom.dat", "macro/CatalogFull.dat", "macro/dndt_constants.dat", "conversion-report.json"):
                self.assertTrue((package / relative).is_file(), relative)
            self.assertEqual(len(report["transmission_corrections"]), 2)
            self.assertEqual({p.name: p.read_bytes() for p in (self.codev / "macro").iterdir()}, original)
            with patch("glass_catalog_ui.QFileDialog.getExistingDirectory", return_value=str(package)):
                self.app.install_codev()
            self.assert_success()
            self.assertTrue(verify(package)["ok"])
            self.assertFalse(any(isinstance(w, QMessageBox) for w in QApplication.topLevelWidgets()))

    def test_directory_failure_is_inline_and_retains_report(self):
        self.app.codev_root.setText(str(self.work / "MISSING_CODEV"))
        output = self.work / "CUSTOM.xml"
        with patch("glass_catalog_ui.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            self.app.export(False)
        self.assertEqual(self.app.last_notice["level"], "error")
        self.assertIn("目录尚未生成", self.app.last_notice["details"])
        report = json.loads(output.with_suffix(".xml.report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["transmission_corrections"]), 2)

    def test_zemax_export_ignores_codev_settings(self):
        self.app.set_output_format("agf")
        self.app.codev_root.setText(str(self.work / "MISSING"))
        output = self.work / "CUSTOM.AGF"
        self.export_to(output)
        self.assertIn("IT .56 1.00005050 1", output.read_text(encoding="utf-16"))
        self.assertFalse(list(self.work.glob("*_CODEV_*")))

    def test_reverse_conversion_uses_format_controls(self):
        xml = self.work / "FROM_CODEV.xml"
        gc.export_catalog(self.app.filtered, xml, catalog_name="FROM_CODEV")
        self.app.clear()
        with patch("glass_catalog_ui.QFileDialog.getOpenFileNames", return_value=([str(xml)], "")):
            self.app.add_files()
        self.app.format_buttons["agf"].click()
        output = self.work / "REVERSE.AGF"
        self.export_to(output)
        result = gc.load_catalog(output).glasses[0]
        self.assertEqual(result.coefficients[:6], gc.load_catalog(self.source).glasses[0].coefficients[:6])
        self.assertEqual(len(result.transmission), 3)

    def test_one_click_codev_install_and_uninstall_without_pickers(self):
        originals = {p.name: p.read_bytes() for p in (self.codev / "macro").iterdir()}
        with patch("glass_catalog_ui.EXPORT_ROOT", self.work / "exports"), \
             patch("glass_catalog_ui.QFileDialog.getExistingDirectory") as folder_picker, \
             patch("glass_catalog_ui.QFileDialog.getSaveFileName") as file_picker:
            self.app.convert_and_install()
            self.assert_success()
            self.assertTrue(verify(self.app.last_bundle)["ok"])
            dialog = self.app.uninstall_codev()
            choice = dialog.findChild(QComboBox, "catalogChoice")
            remove = dialog.findChild(QPushButton, "uninstallSelected")
            self.assertFalse(remove.isEnabled())
            choice.setCurrentText("CUSTOM")
            remove.click()
            self.assert_success()
            folder_picker.assert_not_called()
            file_picker.assert_not_called()
        self.assertFalse((self.codev / "glass/CUSTOM.xml").exists())
        self.assertEqual({p.name: p.read_bytes() for p in (self.codev / "macro").iterdir()}, originals)

    def test_selected_install_scope_for_both_programs(self):
        second = self.work / "SECOND.AGF"
        second.write_text(self.source.read_text().replace("NM TEST ", "NM SECOND "))
        self.app.catalogs.append(gc.load_catalog(second))
        for fmt, output in (("xml", self.codev / "glass/CUSTOM.xml"), ("agf", self.zemax / "CUSTOM.AGF")):
            self.app.apply_filters()
            self.app.table.selectRow(1)
            self.app.install_selected_only.setChecked(True)
            self.app.set_output_format(fmt)
            with patch("glass_catalog_ui.EXPORT_ROOT", self.work / "exports"):
                self.app.convert_and_install()
            self.assert_success()
            self.assertEqual([g.name for g in gc.load_catalog(output).glasses], ["SECOND"])

    def test_status_multiselect_and_transmission_filter(self):
        other = gc.load_catalog(self.source).glasses[0]
        other.name, other.status = "PREFERRED", 1
        self.app.catalogs[0].glasses.append(other)
        self.app.show()
        self.app.filter_button.setChecked(True)
        self.qt_app.processEvents()
        self.app.status.menu().popup(self.app.status.mapToGlobal(QPoint(0, self.app.status.height())))
        self.qt_app.processEvents()
        for value in (0, 1):
            check = self.app.status.checks[f"agf:{value}"]
            QTest.mouseClick(check, Qt.MouseButton.LeftButton, pos=QPoint(8, check.height() // 2))
            self.assertTrue(self.app.status.menu().isVisible())
        self.app.status.menu().close()
        self.app.values["transmission_thickness_mm"].setText("1")
        self.app.values["transmission_min_percent"].setText("98")
        self.assertTrue(self.app.apply_filters())
        self.assertEqual(len(self.app.filtered), 2)
        self.assertEqual(self.app.active_filters["supply_status"], ["agf:0", "agf:1"])
        self.assertIn("99.000%", self.app.table.item(0, 7).text())
        self.app.values["transmission_min_percent"].setText("99.1")
        self.app.apply_filters()
        self.assertEqual(self.app.filtered, [])
        self.app.values["transmission_min_percent"].setText("-1")
        self.assertFalse(self.app.apply_filters())
        self.assertEqual(self.app.last_notice["level"], "error")
        self.app.reset_filters()
        self.assertEqual(len(self.app.filtered), 2)

    def test_codev_status_uses_native_availability_and_filters_it(self):
        xml = self.work / "CDGM.xml"
        gc.export_catalog(self.app.filtered, xml)
        tree = ET.parse(xml)
        tree.find("./Glasses/Glass/Availability").text = "10"
        tree.write(xml, encoding="utf-8", xml_declaration=True)
        self.app.catalogs = [gc.load_catalog(xml)]
        self.app.apply_filters()
        self.assertEqual(self.app.table.item(0, 6).text(), "最高熔炼频率")
        self.assertIn("最高", self.app.table.item(0, 8).text())
        self.app.status.checks["codev:10"].setChecked(True)
        self.app.apply_filters()
        self.assertEqual(len(self.app.filtered), 1)
        self.app.status.clear_selection()
        self.app.status.checks["codev:8"].setChecked(True)
        self.app.apply_filters()
        self.assertEqual(self.app.filtered, [])

    def test_agf_frequency_filter_is_independent_and_hidden_for_codev(self):
        self.source.write_text(self.source.read_text().replace("64.17 0 0", "64.17 0 1 1"))
        self.app.catalogs = [gc.load_catalog(self.source)]
        self.app.apply_filters()
        self.assertEqual(self.app.table.item(0, 6).text(), "优选")
        self.assertIn("1", self.app.table.item(0, 8).text())
        self.app.melt_frequency.checks[2].setChecked(True)
        self.app.apply_filters()
        self.assertEqual(self.app.filtered, [])
        self.app.melt_frequency.checks[1].setChecked(True)
        self.app.apply_filters()
        self.assertEqual(len(self.app.filtered), 1)
        self.app.set_output_format("dat")
        self.assertIsNone(self.app.active_filters["melt_frequency"])
        self.assertTrue(self.app.melt_frequency_row.isHidden())
        self.app.set_output_format("xml")
        self.assertEqual(len(self.app.filtered), 1)

    def test_supplier_picker_filter_export_clear_and_reopen(self):
        source = self.work / "CDGM202509.AGF"
        source.write_bytes(self.source.read_bytes())
        self.app.catalogs = [gc.load_catalog(source)]
        table = self.work / "CDGM202509.csv"
        table.write_text("Glass,Melt Frequency\nTEST,MA\n", encoding="utf-8")
        self.app.supplier_name.setText("OTHER")
        with patch("glass_catalog_ui.QFileDialog.getOpenFileName", return_value=(str(table), "")):
            self.app.choose_supplier_table()
        self.assert_success()
        self.assertEqual(self.app.supplier_name.text(), "CDGM")
        self.assertEqual(self.app.table.item(0, 9).text(), "MA")
        self.assertIn("202509", self.app.table.item(0, 9).toolTip())
        self.assertIn("1/1", self.app.supplier_summary.text())
        self.app.supplier_grade.checks["MA"].setChecked(True)
        self.assertTrue(self.app.apply_filters())
        self.app.set_output_format("agf")
        output = self.work / "GRADED.AGF"
        self.export_to(output)
        report = json.loads(output.with_suffix(".AGF.report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["supplier_data"]["materials"][0]["grade"], "MA")
        self.assertEqual(report["selection"]["filters"]["supplier_grade"], ["MA"])
        reopened = GlassCatalogWindow(settings=dict(self.app.preferences), persist_settings=False)
        try:
            reopened.catalogs = [gc.load_catalog(source)]
            self.assertTrue(reopened.apply_filters())
            self.assertEqual(reopened.table.item(0, 9).text(), "MA")
        finally:
            reopened.close()
            reopened.deleteLater()
        self.app.clear_supplier_table()
        self.assertFalse(self.app.supplier_grade.isEnabled())
        self.assertEqual(self.app.table.item(0, 9).text(), "—")
        self.assertFalse(self.app.preferences["supplier_table"])
        self.assertIsNone(self.app.catalogs[0].glasses[0].supplier_grade)

    def test_invalid_supplier_table_discards_previous_match(self):
        self.app.catalogs[0].glasses[0].catalog = "CDGM"
        path = self.work / "CDGM.csv"
        path.write_text("Glass,Melt Frequency\nTEST,MA\n", encoding="utf-8")
        self.app.supplier_path.setText(str(path))
        self.app.reload_supplier_table()
        self.assertEqual(self.app.table.item(0, 9).text(), "MA")
        path.write_text("Glass,Melt Frequency\nTEST,bad\n", encoding="utf-8")
        self.app.reload_supplier_table()
        self.assertEqual(self.app.last_notice["level"], "error")
        self.assertIsNone(self.app.supplier_reference)
        self.assertFalse(self.app.supplier_grade.isEnabled())
        self.assertEqual(self.app.table.item(0, 9).text(), "—")
        self.assertIn("未载入", self.app.supplier_summary.text())

    def test_dat_uses_installed_picker_and_keeps_conversion_workspace(self):
        (self.codev / "glass").mkdir()
        for name in ("CUSTOM", "OTHER"):
            gc.export_catalog(self.app.filtered, self.codev / "glass" / (name + ".xml"), catalog_name=name)
        self.app.set_output_format("dat")
        self.assertEqual(self.app.filtered, [])
        self.assertTrue(self.app.install_button.isHidden())
        self.assertTrue(self.app.prefix_source.isHidden())
        self.assertEqual(self.app.output_name_label.text(), "清单名称")
        with patch("glass_catalog_ui.QFileDialog.getOpenFileNames") as external_picker:
            dialog = self.app.add_files()
            choices = dialog.findChild(QTableWidget, "expertCatalogChoices")
            self.assertEqual(choices.rowCount(), 2)
            search = dialog.findChild(QLineEdit)
            search.setText("OTHER")
            self.assertTrue(choices.isRowHidden(0))
            search.clear()
            for row in range(choices.rowCount()):
                choices.item(row, 0).setCheckState(Qt.CheckState.Checked)
            dialog.findChild(QPushButton, "loadExpertCatalogs").click()
            external_picker.assert_not_called()
        self.assertEqual(len(self.app.filtered), 2)
        output = self.work / "CANDIDATES.dat"
        self.export_to(output)
        self.assertEqual(output.read_text().splitlines(), ["Catalog\tGlass", "CUSTOM\tTEST", "OTHER\tTEST"])
        self.assertFalse(output.with_suffix(".xml").exists())
        self.app.table.selectRow(1)
        self.export_to(self.work / "SELECTED.dat", True)
        self.assertEqual((self.work / "SELECTED.dat").read_text().splitlines(), ["Catalog\tGlass", "OTHER\tTEST"])
        self.app.values["nd_min"].setText("1.6")
        self.app.apply_filters()
        self.assertEqual(self.app.filtered, [])
        self.app.reset_filters()
        self.assertEqual(len(self.app.filtered), 2)
        self.app.set_output_format("xml")
        self.assertEqual([g.source for g in self.app.filtered], [str(self.source.resolve())])
        self.app.set_output_format("dat")
        self.assertEqual(len(self.app.filtered), 2)
        self.app.clear()
        self.assertEqual(self.app.expert_catalogs, [])
        self.assertEqual(len(self.app.catalogs), 1)

    def test_dat_directory_change_and_removed_library_cannot_export(self):
        (self.codev / "glass").mkdir()
        xml = self.codev / "glass/CUSTOM.xml"
        gc.export_catalog(self.app.filtered, xml)
        self.app.set_output_format("dat")
        dialog = self.app.choose_expert_catalogs()
        dialog.findChild(QTableWidget, "expertCatalogChoices").item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog.findChild(QPushButton, "loadExpertCatalogs").click()
        xml.unlink()
        output = self.work / "MISSING.dat"
        with patch("glass_catalog_ui.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            self.app.export(False)
        self.assertEqual(self.app.last_notice["level"], "error")
        self.assertFalse(output.exists())
        self.app.codev_root.setText(str(self.work / "OTHER_CODEV"))
        self.app.save_preferences()
        self.assertEqual(self.app.expert_catalogs, [])
        self.assertEqual(self.app.filtered, [])
        self.assertIsNone(self.app.choose_expert_catalogs())
        self.assertEqual(self.app.last_notice["level"], "info")
        self.assertEqual(self.app.current_page, "settings")

    def test_dat_small_window_keeps_material_rows_visible_with_filters(self):
        (self.codev / "glass").mkdir()
        xml = self.codev / "glass/CUSTOM.xml"
        gc.export_catalog(self.app.filtered, xml)
        self.app.expert_catalogs = [gc.load_catalog(xml)]
        self.app.set_output_format("dat")
        self.app.resize(1000, 650)
        self.app.show()
        self.app.filter_button.setChecked(True)
        self.app.notify("已载入已安装库", "临时材料库。")
        self.qt_app.processEvents()
        self.assertGreater(self.app.table.viewport().height(), 40)
        for widget in (self.app.export_button, self.app.export_selection_button):
            self.assertTrue(self.app.rect().contains(QRect(widget.mapTo(self.app, QPoint()), widget.size())))
        self.app.set_output_format("xml")
        self.assertEqual(self.app.filter_scroll.maximumHeight(), 140)
        self.app.set_output_format("dat")
        self.qt_app.processEvents()
        self.assertGreater(self.app.table.viewport().height(), 40)

    def test_zemax_manager_install_load_backup_uninstall_restore(self):
        self.app.show_page("zemax")
        self.assertEqual(self.app.zemax_table.rowCount(), 0)
        with patch("glass_catalog_ui.QFileDialog.getOpenFileName", return_value=(str(self.source), "")):
            self.app.install_zemax_file()
        self.assert_success()
        self.assertEqual(self.app.zemax_table.rowCount(), 1)
        self.app.zemax_table.selectRow(0)
        self.app.backup_zemax_selection()
        backup = self.app.last_notice["details"]
        self.app.uninstall_zemax_selection()
        self.assert_success()
        self.assertEqual(self.app.zemax_table.rowCount(), 0)
        with patch("glass_catalog_ui.QFileDialog.getExistingDirectory", return_value=backup):
            self.app.restore_zemax()
        self.assert_success()
        self.app.clear()
        self.app.show_page("zemax")
        self.app.zemax_table.selectRow(0)
        self.app.load_zemax_selection()
        self.assertEqual(self.app.current_page, "browse")
        self.assertEqual([g.name for g in self.app.filtered], ["TEST"])


if __name__ == "__main__":
    unittest.main()
