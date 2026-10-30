import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import glass_catalog as gc
from catalog_fixtures import write_catalog


NBK7_XML = """<?xml version="1.0" encoding="utf-8"?>
<Catalog><Name>SCHOTT</Name><Fullname>Schott</Fullname><Version>3</Version>
<CatalogProperties><DispersionTemperatureIsSameForAllGlasses>true</DispersionTemperatureIsSameForAllGlasses><DispersionTemperature>20</DispersionTemperature><CatalogTransmissionData><Category>Visible</Category><Wavelength>450</Wavelength></CatalogTransmissionData></CatalogProperties>
<Glasses><Glass><GlassName>NBK7</GlassName><NumericName>517642</NumericName>
<EquationType>Glass Manufacturer Sellmeier</EquationType><LowWavelength>290</LowWavelength><HighWavelength>2500</HighWavelength><Availability>0</Availability>
<DispersionCoefficients><Coefficient>1.03961212</Coefficient><Coefficient>0.00600069867</Coefficient><Coefficient>0.231792344</Coefficient><Coefficient>0.0200179144</Coefficient><Coefficient>1.01046945</Coefficient><Coefficient>103.560653</Coefficient></DispersionCoefficients>
<LowCTE><LowerTemperatureLimit>-30</LowerTemperatureLimit><UpperTemperatureLimit>70</UpperTemperatureLimit><Value>71</Value><ExpansionCoeffFactor>10e-7</ExpansionCoeffFactor></LowCTE>
<HighCTE><LowerTemperatureLimit>100</LowerTemperatureLimit><UpperTemperatureLimit>300</UpperTemperatureLimit><Value>83</Value><ExpansionCoeffFactor>10e-7</ExpansionCoeffFactor></HighCTE>
<ManufacturersProperties><Property><Name>Specific_grav</Name><Value>2.51</Value><Category>Mechanical</Category></Property><Property><Name>Transform_temp</Name><Value>557</Value><Category>Thermal</Category></Property></ManufacturersProperties>
<TransmissionCurves><Curve><Category>Visible</Category><Thickness>5</Thickness><Transmission><Wavelength>450</Wavelength><Value>0.999</Value></Transmission><Transmission><Wavelength>650</Wavelength><Value>0.998</Value></Transmission></Curve><Curve><Category>Visible</Category><Thickness>25</Thickness><Transmission><Wavelength>450</Wavelength><Value>0.995</Value></Transmission></Curve></TransmissionCurves>
<FutureExtension keep="yes">native metadata</FutureExtension>
</Glass></Glasses></Catalog>"""


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, text=NBK7_XML, name="source.xml", encoding="utf-8"):
        p = self.work / name
        p.write_text(text, encoding=encoding)
        return p

    def test_supported_formulas_roundtrip_preserves_dispersion_and_transmission(self):
        source = gc.load_catalog(write_catalog(self.work / "SYNTHETIC.AGF"))
        herzberger = self.fixture("NM SYNTH_C 3 0 1.5 50 0 0\nED 8 9 2.5 0 0\n"
                                 "CD 1.5 .001 .0001 .00001 0 0\nLD .4 1.1\nIT .55 .98 5\n", "HERZ.AGF")
        glasses = source.glasses + gc.load_catalog(herzberger).glasses
        output = self.work / "ROUNDTRIP.xml"
        report = gc.export_catalog(glasses, output)
        converted = gc.load_catalog(output)
        self.assertEqual(report["count"], 3)
        gc.export_catalog(converted.glasses, self.work / "RESTORED.AGF")
        restored = gc.load_catalog(self.work / "RESTORED.AGF")
        for original, actual, back in zip(glasses, converted.glasses, restored.glasses):
            self.assertEqual(original.coefficients[:6], actual.coefficients[:6])
            self.assertEqual(original.coefficients[:6], back.coefficients[:6])
            self.assertEqual(actual.availability, gc.AGF_TO_AVAILABILITY[original.status])
            self.assertEqual(actual.ed[:2], original.ed[:2])
            self.assertEqual(original.transmission, back.transmission)
            lo, hi = original.wavelength_range
            for wave in (lo, (lo + hi) / 2, hi):
                self.assertAlmostEqual(gc.refractive_index(original, wave), gc.refractive_index(back, wave), places=13)

    def test_nm_status_is_not_mil_code_and_high_cte_is_independent(self):
        source = gc.load_catalog(write_catalog(self.work / "SYNTHETIC.AGF"))
        glass = source.glasses[0]
        self.assertEqual(glass.mil, 655610)
        self.assertEqual(glass.status, 1)
        self.assertEqual(glass.availability, 0)
        output = self.work / "correct.xml"
        gc.export_catalog([glass], output)
        node = ET.parse(output).find("./Glasses/Glass")
        self.assertEqual(float(node.findtext("LowCTE/Value")), 9.7)
        self.assertEqual(float(node.findtext("HighCTE/Value")), 12.2)

    def test_schott_reference_indices_and_cte_units(self):
        glass = gc.load_catalog(self.fixture()).glasses[0]
        self.assertAlmostEqual(gc.refractive_index(glass, 0.5875618), 1.5168000345, places=9)
        self.assertAlmostEqual(gc.refractive_index(glass, 0.4861327), 1.522376, places=5)
        self.assertAlmostEqual(glass.ed[0], 7.1)
        self.assertAlmostEqual(glass.ed[1], 8.3)
        output = self.work / "NBK7.AGF"
        gc.export_catalog([glass], output, transmission_thickness=5)
        actual = gc.load_catalog(output).glasses[0]
        self.assertEqual(actual.status, 1)
        self.assertEqual(len(actual.transmission), 2)
        self.assertTrue(all(p[2] == 5 for p in actual.transmission))

    def test_multithickness_requires_explicit_choice_without_writing(self):
        glass = gc.load_catalog(self.fixture()).glasses[0]
        output = self.work / "mixed.AGF"
        with self.assertRaisesRegex(gc.CatalogError, "厚度"):
            gc.export_catalog([glass], output)
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(gc.CatalogError, "没有 7"):
            gc.export_catalog([glass], output, transmission_thickness=7)
        self.assertFalse(output.exists())

    def test_native_xml_preserves_unknown_properties_and_categories(self):
        glass = gc.load_catalog(self.fixture()).glasses[0]
        output = self.work / "custom.xml"
        gc.export_catalog([glass], output, catalog_name="CUSTOM")
        root = ET.parse(output).getroot()
        self.assertEqual(root.findtext("Name"), "CUSTOM")
        self.assertEqual(root.findtext("./Glasses/Glass/FutureExtension"), "native metadata")
        self.assertEqual(root.findtext("./CatalogProperties/CatalogTransmissionData/Wavelength"), "450")
        self.assertEqual(len(root.findall("./Glasses/Glass/TransmissionCurves/Curve")), 2)

    def test_native_agf_retains_unknown_formula_records_comments_and_utf16(self):
        text = "CC 中文\n!Special glass: vendor definition\nNM TEST 5 123456 1.5 50 0 3 4\nGC 中文材料\nCD 1.5 0.01 0.02\nMD 80 0.2 500 600 1.1\nBD 0.5 1 2 3\nXY future value\nLD 0.4 1.1\n"
        source = gc.load_catalog(self.fixture(text, "source.AGF", "utf-16"))
        output = self.work / "copy.AGF"
        gc.export_catalog(source.glasses, output)
        exported = output.read_text(encoding="utf-16")
        for line in ("!Special glass: vendor definition", "BD 0.5 1 2 3", "XY future value", "GC 中文材料"):
            self.assertIn(line, exported)
        self.assertEqual(gc.load_catalog(output).glasses[0].coefficients, [1.5, 0.01, 0.02])
        with self.assertRaisesRegex(gc.CatalogError, "不能跨格式"):
            gc.export_catalog(source.glasses, self.work / "bad.xml")

    def test_real_world_bad_optional_data_is_retained_and_reported(self):
        source = self.fixture("NM BAD 1 0 1.5 50 0 0\nCD 2.25 0 0 0 0 0\nOD 32.6 1-2 2 53 1.3 4.3\nLD 0 0\nIT 0.7 12 10\n", "bad.AGF")
        glass = gc.load_catalog(source).glasses[0]
        self.assertEqual(len(glass.issues), 3)
        self.assertFalse(gc.can_convert(glass))
        report = gc.export_catalog([glass], self.work / "native.AGF")
        self.assertEqual(len(report["warnings"]), 3)
        self.assertIn("IT 0.7 12 10", (self.work / "native.AGF").read_text(encoding="utf-16"))
        with self.assertRaises(gc.CatalogError):
            gc.export_catalog([glass], self.work / "bad.xml")

    def test_overrange_transmission_reports_value_instead_of_generic_incompatibility(self):
        source = self.fixture("NM APL5013VH 1 0 1.5439 56 0 0\nCD 2.4 0 0 0 0 0\nLD 0.4047 1.1286\nIT 0.56 1.00005050 1\n", "PLASTIC.AGF")
        glass = gc.load_catalog(source).glasses[0]
        with self.assertRaises(gc.CatalogError) as raised:
            gc.export_catalog([glass], self.work / "CUSTOM.xml", automatic_transmission=False)
        message = str(raised.exception)
        self.assertIn("100.00505%", message)
        self.assertIn("560 nm", message)
        self.assertIn("超过 100%", message)
        self.assertNotIn("--convertible-only", message)

    def test_explicit_transmission_cap_preserves_glass_and_records_original_values(self):
        source = self.fixture("NM APL5013VH 1 0 1.5439 56 0 0\nCD 2.4 0 0 0 0 0\nLD 0.4047 1.1286\nIT 0.55 0.999944556 1\nIT 0.56 1.00005050 1\nIT 0.79 1.00009092 1\n", "PLASTIC.AGF")
        original_bytes = source.read_bytes()
        glass = gc.load_catalog(source).glasses[0]
        output = self.work / "CAPPED.xml"
        report = gc.export_catalog([glass], output, cap_transmission_at_one=True)
        actual = gc.load_catalog(output).glasses[0]
        self.assertEqual(actual.name, "APL5013VH")
        self.assertEqual(actual.coefficients, glass.coefficients)
        self.assertEqual(actual.transmission, [(0.55, 0.999944556, 1.0), (0.56, 1.0, 1.0), (0.79, 1.0, 1.0)])
        self.assertEqual(len(report["transmission_corrections"]), 2)
        self.assertEqual(report["transmission_corrections"][0]["original_value"], 1.00005050)
        self.assertEqual(report["transmission_corrections"][0]["exported_value"], 1.0)
        self.assertEqual(report["transmission_corrections"][0]["source_line"], 5)
        self.assertEqual(source.read_bytes(), original_bytes)
        with self.assertRaises(gc.CatalogError):
            gc.export_catalog([glass], self.work / "STILL_STRICT.xml", automatic_transmission=False)

    def test_small_transmission_overshoot_exports_by_default_and_survives_filter(self):
        source = self.fixture("NM TEST 1 0 1.5 50 0 0\nCD 2.25 0 0 0 0 0\nLD .4 1.1\nIT .55 .99 1\nIT .56 1.00005050 1\nIT .79 1.001 1\n", "SMALL.AGF")
        original = source.read_bytes()
        glass = gc.load_catalog(source).glasses[0]
        self.assertEqual(gc.select_glasses([glass], convertible_only=True), [glass])
        output = self.work / "AUTO.xml"
        report = gc.export_catalog([glass], output)
        self.assertEqual(gc.load_catalog(output).glasses[0].transmission,
                         [(.55, .99, 1.), (.56, 1., 1.), (.79, 1., 1.)])
        self.assertEqual(len(report["transmission_corrections"]), 2)
        self.assertEqual(report["transmission_corrections"][0]["policy"], "automatic_cap_at_one")
        self.assertEqual(report["transmission_corrections"][0]["original_value"], 1.00005050)
        self.assertEqual(source.read_bytes(), original)
        native = self.work / "NATIVE.AGF"
        self.assertEqual(gc.export_catalog([glass], native)["transmission_corrections"], [])
        self.assertIn("IT .56 1.00005050 1", native.read_text(encoding="utf-16"))

    def test_automatic_transmission_policy_still_reports_large_or_invalid_values(self):
        for record in ("IT .56 1.00101 1", "IT .56 -.01 1", "IT .56 1.00005 0"):
            with self.subTest(record=record):
                source = self.fixture("NM TEST 1 0 1.5 50 0 0\nCD 2.25 0 0 0 0 0\nLD .4 1.1\n" + record + "\n", "BAD.AGF")
                glass = gc.load_catalog(source).glasses[0]
                self.assertFalse(gc.can_convert(glass))
                output = self.work / "BAD.xml"
                with self.assertRaises(gc.CatalogError):
                    gc.export_catalog([glass], output)
                self.assertFalse(output.exists())

    def test_filters_combine_inclusively_and_report_misspelled_names(self):
        catalog = gc.load_catalog(write_catalog(self.work / "SYNTHETIC.AGF"))
        actual = gc.select_glasses(catalog.glasses, name="synth_b", nd_min=1.5168, nd_max=1.5168, vd_min=60, vd_max=70, density_max=3)
        self.assertEqual([g.name for g in actual], ["SYNTH_B"])
        with self.assertRaisesRegex(gc.CatalogError, "未找到"):
            gc.select_glasses(catalog.glasses, names=["DOES_NOT_EXIST"])
        with self.assertRaises(gc.CatalogError):
            gc.select_glasses(catalog.glasses, nd_min=2, nd_max=1)

    def test_collision_and_source_overwrite_are_rejected(self):
        text = "NM A-B 1 0 1.5 50 0 0\nCD 2.25 0 0 0 0 0\nLD 0.4 1.1\nNM AB 1 0 1.5 50 0 0\nCD 2.25 0 0 0 0 0\nLD 0.4 1.1\n"
        source = self.fixture(text, "names.AGF")
        glasses = gc.load_catalog(source).glasses
        output = self.work / "exists.xml"
        output.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(gc.CatalogError, "冲突"):
            gc.export_catalog(glasses, output)
        self.assertEqual(output.read_text(), "original")
        with self.assertRaisesRegex(gc.CatalogError, "源库相同"):
            gc.export_catalog(glasses, source)

    def test_herzberger_ir_coefficients_roundtrip_without_visible_extrapolation(self):
        text = "NM HWS1 3 0 1 0 0 0 4\nCD 2.6209608 .065486281 .098915134 -.0002050585 3.4955962E-7 -1.2725532E-9\nLD 1 14\n"
        glass = gc.load_catalog(self.fixture(text, "IR.AGF")).glasses[0]
        output = self.work / "IR.xml"
        gc.export_catalog([glass], output)
        back = gc.load_catalog(output).glasses[0]
        self.assertIsNone(back.nd)
        self.assertEqual(back.coefficients, glass.coefficients)
        for wave in (1, 2, 4, 8, 14):
            self.assertEqual(gc.refractive_index(glass, wave), gc.refractive_index(back, wave))
        with self.assertRaisesRegex(gc.CatalogError, "有效范围"):
            gc.refractive_index(back, .5875618)

    def test_cli_json_success_and_failure(self):
        source = self.fixture()
        command = [sys.executable, "-X", "utf8", str(ROOT / "glass_catalog.py")]
        result = subprocess.run([*command, "inspect", str(source), "--json"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["selected"], 1)
        self.assertEqual(json.loads(result.stdout)["glasses"][0]["transmission_thicknesses_mm"], [5, 25])
        self.assertEqual(json.loads(result.stdout)["glasses"][0]["transmission_point_count"], 3)
        result = subprocess.run([*command, "convert", str(source), "--output", str(self.work / "CUSTOM.AGF"), "--json"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])
        result = subprocess.run([*command, "convert", str(source), "--output", str(self.work / "CUSTOM.AGF"),
                                 "--transmission-thickness", "5", "--json"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["count"], 1)
        self.assertTrue(Path(report["report"]).exists())


if __name__ == "__main__":
    unittest.main()
