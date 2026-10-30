from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import glass_catalog as gc
import zemax_catalog_manager as zm


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.source = self.work / "SOURCE.AGF"
        self.source.write_text("NM TEST 2 0 1.5168 64.17 0 0\n"
                               "CD 1.03961212 .00600069867 .231792344 .0200179144 1.01046945 103.560653\n"
                               "LD .29 2.5\nIT .5 .8 5\nIT .6 1 5\n")
        self.glass = gc.load_catalog(self.source).glasses[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_status_is_union_with_other_filters_intersection(self):
        glasses = []
        for i in range(5):
            glass = deepcopy(self.glass)
            glass.name, glass.status = f"G{i}", i
            glasses.append(glass)
        result = gc.select_glasses(glasses, status=[0, 1, 4], nd_min=1.5, nd_max=1.6)
        self.assertEqual([g.name for g in result], ["G0", "G1", "G4"])
        self.assertEqual([g.status for g in gc.select_glasses(glasses, status=2)], [2])
        self.assertEqual(gc.select_glasses(glasses, status=[0, 1], nd_min=1.6), [])

    def test_internal_transmission_interpolation_and_thickness_scaling(self):
        self.assertAlmostEqual(gc.transmission_at(self.glass, 500, 5), .8)
        self.assertAlmostEqual(gc.transmission_at(self.glass, 550, 10), .9 ** 2)
        self.assertAlmostEqual(gc.transmission_at(self.glass, 550, 2.5), math.sqrt(.9))
        self.assertEqual(gc.transmission_at(self.glass, 600, 10), 1)
        self.assertIsNone(gc.transmission_at(self.glass, 601, 5))
        self.assertIsNone(gc.transmission_at(self.glass, 499, 5))
        self.glass.transmission += [(.5, .7, 10), (.6, .9, 10)]
        self.assertAlmostEqual(gc.transmission_at(self.glass, 550, 10), .8)

    def test_transmission_filter_boundaries_missing_data_and_bad_inputs(self):
        query = dict(transmission_wavelength_nm=550, transmission_thickness_mm=10)
        missing = deepcopy(self.glass)
        missing.transmission = []
        glasses = [self.glass, missing]
        self.assertEqual(gc.select_glasses(glasses, **query, transmission_min_percent=81, transmission_max_percent=81), [self.glass])
        self.assertEqual(gc.select_glasses(glasses, **query, transmission_min_percent=82), [])
        for options in (dict(transmission_min_percent=90), dict(**query, transmission_min_percent=-1),
                        dict(**query, transmission_max_percent=101),
                        dict(transmission_wavelength_nm=550, transmission_thickness_mm=0),
                        dict(**query, transmission_min_percent=99, transmission_max_percent=98)):
            with self.subTest(options=options), self.assertRaises(gc.CatalogError):
                gc.select_glasses(glasses, **options)

    def test_transmission_zero_and_small_overshoot_use_confirmed_policy(self):
        self.glass.transmission = [(.5, 0, 1)]
        self.assertEqual(gc.transmission_at(self.glass, 500, 10), 0)
        self.source.write_text(self.source.read_text().replace("IT .5 .8 5", "IT .5 1.00009 5"))
        original = gc.load_catalog(self.source).glasses[0]
        self.assertEqual(gc.transmission_at(original, 500, 10), 1)
        self.assertEqual(original.transmission_above_one[0]["original_value"], 1.00009)

    def test_cli_has_multistatus_and_percent_filter(self):
        command = [sys.executable, "-X", "utf8", str(ROOT / "glass_catalog.py"), "inspect", str(self.source),
                   "--status", "0", "1", "--it-at-nm", "550", "--it-thickness-mm", "10", "--it-min", "80", "--json"]
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["selected"], 1)
        self.assertAlmostEqual(result["glasses"][0]["filter_internal_transmission_percent"], 81)

    def test_codev_native_supply_labels_and_filter_keep_frequency(self):
        path = self.work / "CDGM.xml"
        gc.export_catalog([self.glass], path)
        root = ET.parse(path).getroot()
        container = root.find("Glasses")
        template = deepcopy(container[0])
        container.clear()
        expected = {8: "请询厂家", 10: "最高熔炼频率", 11: "较高熔炼频率", 12: "低熔炼频率", 14: "很低熔炼频率"}
        for value in expected:
            node = deepcopy(template)
            node.find("GlassName").text = f"G{value}"
            node.find("Availability").text = str(value)
            container.append(node)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        glasses = gc.load_catalog(path).glasses
        self.assertEqual({g.availability: g.supply_label for g in glasses}, expected)
        self.assertEqual([g.name for g in gc.select_glasses(glasses, supply_status=["codev:10", "codev:11"])], ["G10", "G11"])
        self.assertEqual(glasses[1].summary()["supply_status"], "codev:10")
        self.assertIn("最高", glasses[1].melt_frequency_label)

    def test_agf_melt_frequency_is_separate_from_supply_status(self):
        record = self.source.read_text()
        self.source.write_text("".join(record.replace("NM TEST 2 0 1.5168 64.17 0 0", f"NM G{value} 2 0 1.5168 64.17 0 1 {value}")
                                       for value in range(1, 6)))
        glasses = gc.load_catalog(self.source).glasses
        self.assertEqual([g.melt_frequency for g in glasses], [1, 2, 3, 4, 5])
        self.assertEqual({g.supply_label for g in glasses}, {"优选"})
        selected = gc.select_glasses(glasses, supply_status=["agf:1"], melt_frequency=[1, 2, 3])
        self.assertEqual([g.name for g in selected], ["G1", "G2", "G3"])
        output = self.work / "FREQUENT.AGF"
        gc.export_catalog(selected, output)
        self.assertEqual([g.melt_frequency for g in gc.load_catalog(output).glasses], [1, 2, 3])
        for options in ({"supply_status": ["codev:99"]}, {"melt_frequency": [6]}):
            with self.subTest(options=options), self.assertRaises(gc.CatalogError):
                gc.select_glasses(glasses, **options)

    def test_native_supply_and_melt_frequency_cli(self):
        self.source.write_text(self.source.read_text().replace("64.17 0 0", "64.17 0 1 1"))
        command = [sys.executable, "-X", "utf8", str(ROOT / "glass_catalog.py"), "inspect", str(self.source),
                   "--supply-status", "agf:1", "--melt-frequency", "1", "2", "3", "--json"]
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["glasses"][0]["supply_label"], "优选")
        self.assertEqual(result["glasses"][0]["melt_frequency"], 1)

    def test_expert_source_references_preserve_catalog_and_ir_material(self):
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        xml = codev / "glass/CAT.xml"
        gc.export_catalog([self.glass], xml, catalog_name="CAT")
        glass = gc.load_catalog(xml).glasses[0]
        # Candidate lists need no visible-spectrum nd or dispersion conversion.
        glass.nd = glass.vd = None
        glass.wavelength_range = (3, 12)
        output = self.work / "LIST.dat"
        report = gc.export_catalog([glass], output, expert_reference="source", codev_root=codev)
        self.assertEqual(output.read_bytes(), b"Catalog\tGlass\r\nCAT\tTEST\r\n")
        self.assertEqual(report["reference_mode"], "source")
        self.assertNotIn("companion_xml", report)
        self.assertFalse(output.with_suffix(".xml").exists())

    def test_expert_rejects_agf_and_new_library_without_writing_companion(self):
        for reference in ("auto", "source", "new"):
            with self.subTest(reference=reference), self.assertRaisesRegex(gc.CatalogError, "已安装"):
                gc.export_catalog([self.glass], self.work / "LIST.dat", expert_reference=reference)
        self.assertFalse((self.work / "LIST.dat").exists())
        self.assertFalse((self.work / "LIST.xml").exists())

    def test_expert_missing_reference_and_duplicate_are_reported(self):
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        xml = codev / "glass/CAT.xml"
        gc.export_catalog([self.glass], xml)
        glass = gc.load_catalog(xml).glasses[0]
        output = self.work / "MATCH.dat"
        report = gc.export_catalog([glass], output, codev_root=codev)
        self.assertEqual(report["reference_verification"], {"checked": True, "missing": []})
        glass.name = "NO_SUCH_GLASS"
        with self.assertRaisesRegex(gc.CatalogError, "CAT/NO_SUCH_GLASS"):
            gc.export_catalog([glass], self.work / "MISSING.dat", codev_root=codev)
        self.assertFalse((self.work / "MISSING.dat").exists())
        glass.name = "TEST"
        with self.assertRaisesRegex(gc.CatalogError, "重复"):
            gc.export_catalog([glass, glass], self.work / "DUP.dat", codev_root=codev)
        self.assertFalse((self.work / "DUP.dat").exists())
        with self.assertRaisesRegex(gc.CatalogError, "已安装的 XML"):
            gc.export_catalog([self.glass], self.work / "BAD.dat", expert_reference="source")

    def test_expert_requires_installed_sources_and_rechecks_current_materials(self):
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        external = self.work / "CAT.xml"
        gc.export_catalog([self.glass], external)
        installed = codev / "glass/CAT.xml"
        installed.write_bytes(external.read_bytes())
        glass = gc.load_catalog(external).glasses[0]
        output = self.work / "INVALID.dat"
        for root in (None, self.work / "not_CODEV", codev):
            with self.subTest(root=root), self.assertRaises(gc.CatalogError):
                gc.export_catalog([glass], output, codev_root=root)
        glass = gc.load_catalog(installed).glasses[0]
        installed.write_text(installed.read_text().replace("<GlassName>TEST</GlassName>", "<GlassName>UPDATED</GlassName>"))
        with self.assertRaisesRegex(gc.CatalogError, "CAT/TEST"):
            gc.export_catalog([glass], output, codev_root=codev)
        installed.unlink()
        with self.assertRaisesRegex(gc.CatalogError, "已安装"):
            gc.export_catalog([glass], output, codev_root=codev)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix(".dat.report.json").exists())

    def test_expert_multiple_installed_libraries_preserve_names_and_files(self):
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        glasses, originals = [], {}
        for filename, name in (("vendor_a.xml", "CAT_A"), ("CAT_B.xml", "CAT_B")):
            path = codev / "glass" / filename
            gc.export_catalog([self.glass], path, catalog_name=name)
            originals[path] = path.read_bytes()
            glasses.extend(gc.load_catalog(path).glasses)
        output = self.work / "CANDIDATES.dat"
        report = gc.export_catalog(glasses, output, catalog_name="FILE_ONLY", codev_root=codev)
        self.assertEqual(output.read_bytes(), b"Catalog\tGlass\r\nCAT_A\tTEST\r\nCAT_B\tTEST\r\n")
        self.assertEqual(report["reference_catalogs"], ["CAT_A", "CAT_B"])
        self.assertEqual(report["reference_verification"], {"checked": True, "missing": []})
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertFalse(output.with_suffix(".xml").exists())

    def test_expert_cli_uses_installed_xml_and_rejects_agf(self):
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        xml = codev / "glass/CAT.xml"
        gc.export_catalog([self.glass], xml)
        for source, expected in ((xml, 0), (self.source, 2)):
            process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "glass_catalog.py"), "convert", str(source),
                                      "--output", str(self.work / "CLI.dat"), "--codev-root", str(codev), "--json"],
                                     capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual(report["ok"], expected == 0)
            if expected == 0:
                self.assertTrue(report["reference_verification"]["checked"])

    def test_zemax_install_update_backup_uninstall_restore_keeps_other_libraries(self):
        root = self.work / "Glasscat"
        first = zm.install(self.source, root, "CUSTOM")
        self.assertTrue(first["ok"])
        zm.install(self.source, root, "OTHER")
        cached = root / "CUSTOM.BGF"
        cached.write_bytes(b"old generated cache")
        updated = zm.install(self.source, root, "CUSTOM")
        self.assertEqual((Path(updated["backup"]) / "CUSTOM.BGF").read_bytes(), b"old generated cache")
        self.assertFalse(cached.exists())
        backup = zm.backup_catalog("CUSTOM", root)
        removed = zm.uninstall("CUSTOM", root)
        self.assertEqual(removed["status"], "files_removed")
        self.assertFalse((root / "CUSTOM.AGF").exists())
        self.assertEqual((root / "OTHER.AGF").read_bytes(), self.source.read_bytes())
        restored = zm.restore(backup["backup"], root)
        self.assertEqual(restored["status"], "file_restored")
        self.assertEqual((root / "CUSTOM.AGF").read_bytes(), self.source.read_bytes())
        self.assertEqual(zm.list_catalogs(root)["count"], 2)

    def test_zemax_rejects_bad_input_before_touching_installed_files(self):
        root = self.work / "Glasscat"
        zm.install(self.source, root, "CUSTOM")
        before = (root / "CUSTOM.AGF").read_bytes()
        for name in ("../CUSTOM", "C:\\CUSTOM", "bad/name"):
            with self.subTest(name=name), self.assertRaises(gc.CatalogError):
                zm.uninstall(name, root)
        bad = self.work / "BAD.AGF"
        bad.write_text("not a glass catalog")
        with self.assertRaises(gc.CatalogError):
            zm.install(bad, root, "CUSTOM")
        self.assertEqual((root / "CUSTOM.AGF").read_bytes(), before)

    def test_zemax_cli_dispatch_from_shared_entry(self):
        root = self.work / "Glasscat"
        for args in (["install", str(self.source)], ["list"], ["backup", "SOURCE"], ["uninstall", "SOURCE"]):
            command = [sys.executable, "-X", "utf8", str(ROOT / "glass_catalog.py"), "zemax", *args,
                       "--glasscat", str(root), "--json"]
            process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(json.loads(process.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
