from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import glass_catalog as gc
from catalog_fixtures import write_catalog
from supplier_catalog import enrich_glasses, load_supplier_table


class SupplierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.source = write_catalog(self.work / "CDGM202509.AGF")
        self.glasses = gc.load_catalog(self.source).glasses

    def tearDown(self):
        self.temp.cleanup()

    def table(self, text="Glass,Melt Frequency\nSYNTH_A,MA\nSYNTH_B,B\n", filename="CDGM202509.csv", encoding="utf-8-sig"):
        path = self.work / filename
        path.write_text(text, encoding=encoding)
        return path

    def cli(self, *args):
        output = StringIO()
        with redirect_stdout(output):
            code = gc.main([*map(str, args), "--json"])
        return code, json.loads(output.getvalue())

    def test_csv_source_version_and_original_records_are_preserved(self):
        path = self.table()
        table = load_supplier_table(path)
        self.assertEqual(table.manufacturer, "CDGM")
        self.assertEqual(table.version, "202509")
        self.assertEqual(table.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        enriched = enrich_glasses(self.glasses, table)
        self.assertEqual([g.supplier_grade for g in enriched], ["MA", "B"])
        self.assertTrue(all(g.supplier_grade is None for g in self.glasses))
        for before, after in zip(self.glasses, enriched):
            self.assertEqual(before.coefficients, after.coefficients)
            self.assertEqual(before.melt_frequency, after.melt_frequency)
            self.assertEqual(before.raw_agf, after.raw_agf)

    def test_tsv_chinese_headers_and_gb18030(self):
        path = self.table("说明\n牌号\t生产频率\nSYNTH_A\tma\nSYNTH_B\tD\n", "ACME.tsv", "gb18030")
        table = load_supplier_table(path, "ACME")
        self.assertEqual(table.grades, {"SYNTH_A": "MA", "SYNTH_B": "D"})
        self.assertIsNone(table.version)

    def test_xlsx_sparse_columns_shared_and_inline_strings(self):
        path = self.work / "CDGM202510.xlsx"
        files = {
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="optical glass" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="/xl/worksheets/sheet1.xml"/></Relationships>',
            "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Glass</t></si><si><r><t>Melt </t></r><r><t>Frequency</t></r></si><si><t>SYNTH_A</t></si></sst>',
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="HV1" t="s"><v>1</v></c></row><row r="2"><c r="A2" t="s"><v>2</v></c><c r="HV2" t="inlineStr"><is><t>MA</t></is></c></row><row r="3"><c r="A3" t="inlineStr"><is><t>SYNTH_B</t></is></c><c r="HV3" t="inlineStr"><is><t>C</t></is></c></row></sheetData></worksheet>',
        }
        with zipfile.ZipFile(path, "w") as archive:
            for filename, content in files.items():
                archive.writestr(filename, content)
        table = load_supplier_table(path)
        self.assertEqual(table.grades, {"SYNTH_A": "MA", "SYNTH_B": "C"})
        self.assertEqual(table.version, "202510")

    def test_matching_isolates_manufacturer_and_does_not_fuzzy_guess(self):
        table = load_supplier_table(self.table("Glass,Melt Frequency\nH-K9L,MA\n"))
        glasses = [replace(self.glasses[0], name=" h k9l ", catalog="cdgm-202509"),
                   replace(self.glasses[0], name="H-K9L", catalog="OTHER"),
                   replace(self.glasses[0], name="H-K9L", catalog="CDGMOTHER"),
                   replace(self.glasses[0], name="H-K9LGT", catalog="CDGM"),
                   replace(self.glasses[0], name="H-K9L", catalog="MY_CUSTOM")]
        self.assertEqual([g.supplier_grade for g in enrich_glasses(glasses, table)], ["MA", None, None, None, None])

    def test_conflicting_grades_are_rejected_but_same_duplicates_are_allowed(self):
        path = self.table("Glass,Melt Frequency\nH-K9L,MA\nHK9L,D\n")
        with self.assertRaisesRegex(gc.CatalogError, "冲突"):
            load_supplier_table(path)
        path.write_text("Glass,Melt Frequency\nH-K9L,MA\nHK9L,MA\n", encoding="utf-8")
        self.assertEqual(load_supplier_table(path).grades, {"HK9L": "MA"})

    def test_unknown_manufacturer_missing_headers_and_invalid_grade_explain_error(self):
        with self.assertRaisesRegex(gc.CatalogError, "厂家"):
            load_supplier_table(self.table(filename="unknown.csv"))
        for content, error in (("Glass,Price\nSYNTH_A,10\n", "表头"),
                               ("Glass,Melt Frequency\nSYNTH_A,1\n", "MA/A/B/C/D")):
            with self.subTest(content=content), self.assertRaisesRegex(gc.CatalogError, error):
                load_supplier_table(self.table(content))

    def test_grade_filter_is_or_and_independent_of_software_frequency(self):
        enriched = enrich_glasses(self.glasses, load_supplier_table(self.table()))
        self.assertEqual([g.name for g in gc.select_glasses(enriched, supplier_grade=["MA", "B"])], ["SYNTH_A", "SYNTH_B"])
        self.assertEqual([g.name for g in gc.select_glasses(enriched, supplier_grade=["B"], melt_frequency=[1])], ["SYNTH_B"])
        self.assertEqual(gc.select_glasses(enriched, supplier_grade=["B"], melt_frequency=[2]), [])

    def test_cli_requires_table_and_returns_matched_count(self):
        code, result = self.cli("inspect", self.source, "--supplier-grade", "MA")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        code, result = self.cli("inspect", self.source, "--supplier-table", self.table(), "--supplier-grade", "MA", "A")
        self.assertEqual(code, 0)
        self.assertEqual(result["supplier_table"]["matched"], 2)
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["glasses"][0]["supplier_grade"], "MA")

    def test_conversion_and_dat_reports_keep_reference_without_rewriting_native_codes(self):
        path = self.table()
        output = self.work / "CUSTOM.xml"
        code, report = self.cli("convert", self.source, "--output", output, "--supplier-table", path, "--supplier-grade", "B")
        self.assertEqual(code, 0)
        reference = report["supplier_data"]["references"][0]
        self.assertEqual(reference["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report["supplier_data"]["materials"][0]["grade"], "B")
        glass = gc.load_catalog(output).glasses[0]
        self.assertEqual(glass.availability, gc.AGF_TO_AVAILABILITY[self.glasses[1].status])
        codev = self.work / "CODEV"
        (codev / "glass").mkdir(parents=True)
        installed = codev / "glass/CDGM.xml"
        gc.export_catalog(self.glasses, installed, catalog_name="CDGM")
        code, report = self.cli("convert", installed, "--output", self.work / "CANDIDATES.dat", "--codev-root", codev,
                                "--supplier-table", path, "--supplier-grade", "MA")
        self.assertEqual(code, 0)
        self.assertEqual(report["supplier_data"]["materials"][0]["grade"], "MA")
        self.assertEqual((self.work / "CANDIDATES.dat").read_text(), "Catalog\tGlass\nCDGM\tSYNTH_A\n")


if __name__ == "__main__":
    unittest.main()
