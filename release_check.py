"""Offline runtime check used to validate the distributed Windows executable."""

import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET


def run(report_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    try:
        from PySide6.QtCore import QPoint, QRect, Qt
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QFileDialog, QTableWidget, QPushButton
        import glass_catalog as gc
        from glass_catalog_ui import GlassCatalogWindow, create_application
        import glass_catalog_ui as ui
        import zemax_catalog_manager as zm
        from codev_catalog_bundle import verify
        app = create_application()
        result["checks"].append("正常启动初始化、Windows应用标识与ctypes加载")
        for name in ("msyh.ttc", "msyhl.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
        app.setFont(QFont("Microsoft YaHei UI", 10))
        with tempfile.TemporaryDirectory(prefix="glass_release_") as temporary:
            work = Path(temporary)
            ui.EXPORT_ROOT = work / "exports"
            codev = work / "CODEV"
            (codev / "macro").mkdir(parents=True)
            headers = "Catalog Glass Index V-value NF-NC DPF Price Avail Bubble Stain".split()
            headers += ["Low WL", "High WL", *"Price_gob Specific_grav Manufacture_date date_received date_index_changed Equation_type Replacement Low_exp_coeff High_exp_coeff Transform_temp Knoop Poisson Young Acid_resist Acid_resist_powder Acid_resist_surface Rigidity Water_resist".split()]
            (codev / "macro/CatalogFull.dat").write_text("\t".join(headers) + "\n", encoding="utf-8")
            thermal = "Glass Catalog Formula A1/B1 A2/C1 A3/B2 A4/C2 A5/B3 A6/C3 D0 D1 D2 E0 E1 lambda MeasuredTemp Alpha_lowT Tmin_al Tmax_al Alpha_highT Tmin_ah Tmax_ah".split()
            (codev / "macro/dndt_constants.dat").write_text("Version#3\n" + "\t".join(thermal) + "\n", encoding="utf-8")
            original_tables = {p.name: p.read_bytes() for p in (codev / "macro").iterdir()}
            source = work / "CDGM202509.AGF"
            record = "NM TEST 1 0 1.5 50 0 0 1\nCD 2.25 0 .008 0 0 0\nLD .3 2.5\nIT .5 .8 5\nIT .6 1 5\n"
            source.write_text(record + record.replace("NM TEST ", "NM SECOND ").replace("50 0 0", "50 0 1"), encoding="utf-8")
            w = GlassCatalogWindow(settings={"codev_root": str(codev), "zemax_glasscat": str(work / "Glasscat")},
                                   persist_settings=False)
            w.catalogs = [gc.load_catalog(source)]
            w.catalog_name.setText("RUNTIME")
            w.status.checks["agf:0"].setChecked(True)
            w.status.checks["agf:1"].setChecked(True)
            w.melt_frequency.checks[1].setChecked(True)
            w.values["transmission_min_percent"].setText("80")
            assert w.apply_filters() and len(w.filtered) == 2
            assert abs(gc.transmission_at(w.filtered[0], 550, 10) - .81) < 1e-12
            assert w.filtered[0].melt_frequency == 1 and "1" in w.table.item(0, 8).text()
            result["checks"].append("多状态与内透过率筛选")
            supplier_table = work / "CDGM202509.csv"
            supplier_table.write_text("Glass,Melt Frequency\nTEST,MA\nSECOND,B\n", encoding="utf-8")
            w.supplier_path.setText(str(supplier_table))
            w.reload_supplier_table()
            assert w.last_notice["level"] == "success", w.last_notice
            assert w.table.item(0, 9).text() == "MA" and w.table.item(1, 9).text() == "B"
            w.supplier_grade.checks["MA"].setChecked(True)
            assert w.apply_filters() and len(w.filtered) == 1
            graded = gc.export_catalog(w.filtered, work / "GRADED.xml")
            assert graded["supplier_data"]["materials"][0]["grade"] == "MA"
            assert graded["supplier_data"]["references"][0]["version"] == "202509"
            w.clear_supplier_table()
            assert len(w.filtered) == 2 and w.table.item(0, 9).text() == "—"
            result["checks"].append("厂家表读取、字母筛选、来源报告与清除")
            extra_source = work / "OTHER.AGF"
            extra_source.write_text(record.replace("NM TEST ", "NM EXTRA "), encoding="utf-8")
            original_extra = extra_source.read_bytes()
            w.catalogs.append(gc.load_catalog(extra_source))
            assert w.apply_filters() and len(w.filtered) == 3
            w.source_catalog.setCurrentIndex(w.source_catalog.findData(str(extra_source.resolve())))
            w.show()
            app.processEvents()
            assert w.grab().save(str(Path(report_path).with_name(Path(report_path).stem + "_Sources.png")))
            w.remove_source_button.click()
            assert len(w.catalogs) == 1 and len(w.filtered) == 2
            assert w.active_filters["transmission_min_percent"] == 80
            assert w.source_catalog.count() == 1 and extra_source.read_bytes() == original_extra
            result["checks"].append("单库移除同步材料与来源列表、保留筛选和原文件")
            w.update_catalog_name(force=True)
            assert w.catalog_name.text().startswith("CDGM202509_FILTERED_")
            w.catalog_name.setText("RUNTIME")
            w.apply_filters()
            assert w.catalog_name.text() == "RUNTIME"
            result["checks"].append("来源与条件自动命名、手工名称保留")
            for fmt, target in (("xml", "CODE V"), ("agf", "Zemax")):
                w.set_output_format(fmt)
                assert target in w.install_button.text()
                w.convert_and_install()
                assert w.last_notice["level"] == "success", w.last_notice
            assert verify(w.last_bundle)["ok"]
            result["checks"].extend(["CODE V 转换安装与两张总表", "Zemax 转换安装", "格式与主按钮联动"])
            native_path = work / "NATIVE.xml"
            gc.export_catalog(w.catalogs[0].glasses[:1], native_path)
            native_tree = ET.parse(native_path)
            native_tree.find("./Glasses/Glass/Availability").text = "10"
            native_tree.write(native_path, encoding="utf-8", xml_declaration=True)
            original_catalogs = w.catalogs
            w.catalogs = [gc.load_catalog(native_path)]
            w.apply_filters()
            assert w.table.item(0, 6).text() == "最高熔炼频率"
            w.status.checks["codev:10"].setChecked(True)
            assert w.apply_filters() and len(w.filtered) == 1
            w.status.clear_selection()
            w.catalogs = original_catalogs
            result["checks"].append("CODE V 原生供应状态与 Zemax 独立熔炼频率")
            w.set_output_format("dat")
            assert not w.filtered and w.install_button.isHidden()
            assert "EXPERT" in w.catalog_name.text()
            dialog = w.choose_expert_catalogs()
            choices = dialog.findChild(QTableWidget, "expertCatalogChoices")
            assert choices.rowCount() == 1
            choices.item(0, 0).setCheckState(Qt.CheckState.Checked)
            dialog.findChild(QPushButton, "loadExpertCatalogs").click()
            assert len(w.filtered) == 2
            originals = {p: p.read_bytes() for p in codev.rglob("*") if p.is_file()}
            output = work / "CANDIDATES.dat"
            original_picker = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = lambda *args: (str(output), "")
            try:
                w.export(False)
            finally:
                QFileDialog.getSaveFileName = original_picker
            assert w.last_notice["level"] == "success", w.last_notice
            assert output.read_bytes().startswith(b"Catalog\tGlass\r\nRUNTIME\tTEST")
            assert w.catalog_name.text() == "CANDIDATES"
            assert not output.with_suffix(".xml").exists()
            assert json.loads(output.with_suffix(".dat.report.json").read_text(encoding="utf-8"))["reference_verification"]["checked"]
            assert all(p.read_bytes() == value for p, value in originals.items())
            result["checks"].append("已安装库选择、DAT 引用核对与软件目录保持原样")
            dat_catalogs = list(w.expert_catalogs)
            w.remove_source_button.click()
            assert not w.expert_catalogs and not w.filtered and not w.remove_source_button.isEnabled()
            assert len(w.catalogs) == 1 and all(p.read_bytes() == value for p, value in originals.items())
            w.expert_catalogs = dat_catalogs
            assert w.apply_filters() and len(w.filtered) == 2
            result["checks"].append("DAT 来源单独移除、不影响转换来源和已安装库")
            w.show()
            app.processEvents()
            assert w.grab().save(str(Path(report_path).with_name(Path(report_path).stem + "_DAT.png")))
            w.resize(1000, 650)
            w.filter_button.setChecked(True)
            app.processEvents()
            assert w.table.viewport().height() > 40
            assert w.grab().save(str(Path(report_path).with_name(Path(report_path).stem + "_DAT_small.png")))
            result["checks"].append("DAT 小窗口展开筛选后材料与操作可见")
            w.show_page("zemax")
            assert w.zemax_table.rowCount() == 1
            w.zemax_table.selectRow(0)
            app.processEvents()
            assert w.grab().save(str(Path(report_path).with_name(Path(report_path).stem + "_Zemax.png")))
            w.backup_zemax_selection()
            backup = w.last_notice["details"]
            w.uninstall_zemax_selection()
            assert not (work / "Glasscat/RUNTIME.AGF").exists()
            zm.restore(backup, work / "Glasscat")
            assert zm.list_catalogs(work / "Glasscat")["count"] == 1
            result["checks"].append("Zemax 管理备份、卸载与恢复")
            w.show_page("codev")
            assert w.codev_table.rowCount() == 1 and w.output_bar.isHidden()
            w.codev_table.selectRow(0)
            app.processEvents()
            assert w.grab().save(str(Path(report_path).with_name(Path(report_path).stem + "_CODEV.png")))
            w.codev_load_button.click()
            assert w.current_page == "browse" and w.dat_mode
            w.show_page("codev")
            w.codev_table.selectRow(0)
            w.codev_uninstall_button.click()
            assert w.last_notice["level"] == "success", w.last_notice
            assert w.codev_table.rowCount() == 0
            assert all((codev / "macro" / name).read_bytes() == value for name, value in original_tables.items())
            result["checks"].append("CODE V 管理页列出、载入与卸载后两张总表保持原内容")
            w.show_page("browse")
            w.set_output_format("agf")
            assert w.catalog_name.text() == "RUNTIME"
            w.resize(1000, 650)
            w.show()
            w.filter_button.setChecked(True)
            w.notify("独立程序运行检查通过", "所有安装卸载都在临时目录中执行。")
            app.processEvents()
            for widget in (w.install_button, w.export_button, w.nav_buttons["codev"], w.nav_buttons["zemax"],
                           w.source_catalog, w.remove_source_button):
                assert w.rect().contains(QRect(widget.mapTo(w, QPoint()), widget.size()))
            assert w.table.viewport().height() > 40
            assert w.notice.isVisible() and not w.notice_details.isVisible()
            result["checks"].append("真实字体、小窗口、无声页面内提示")
            assert w.grab().save(str(Path(report_path).with_suffix(".png")))
            w.close()
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 2
