from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import codev_catalog_bundle as bundle
from glass_catalog import CatalogError, export_catalog, load_catalog
from catalog_fixtures import write_catalog, write_codev_tables


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.work=Path(self.temp.name)
        self.root=self.work/'CODEV'
        tables=write_codev_tables(self.root)
        self.full=tables['CatalogFull.dat']
        self.thermal=tables['dndt_constants.dat']
        self.synthetic=write_catalog(self.work/'SYNTHETIC.AGF')
        glasses=load_catalog(self.synthetic).glasses
        self.xml=self.work/'CUSTOM.xml'
        export_catalog(glasses[:2],self.xml)

    def tearDown(self):
        self.temp.cleanup()

    def test_list_installed_catalogs_keeps_readable_and_broken_files_without_writes(self):
        directory = self.root / "glass"
        directory.mkdir()
        (directory / "CUSTOM.xml").write_bytes(self.xml.read_bytes())
        (directory / "BROKEN.XML").write_text("<Catalog>")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = bundle.list_catalogs(self.root)
        self.assertTrue(result["exists"])
        self.assertEqual(result["count"], 2)
        broken, custom = result["catalogs"]
        self.assertIsNone(broken["count"])
        self.assertIn("error", broken)
        self.assertEqual(custom["count"], 2)
        self.assertEqual(Path(custom["path"]), (directory / "CUSTOM.xml").resolve())
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse(bundle.list_catalogs(self.work / "MISSING")["exists"])

    def test_prepare_preserves_other_catalog_rows_and_thermal_version(self):
        target=self.work/'bundle'
        result=bundle.prepare(self.xml,self.root,target)
        self.assertEqual(result['count'],2)
        merged=(target/'macro'/'CatalogFull.dat').read_bytes()
        for line in self.full.splitlines()[1:]: self.assertIn(line,merged)
        thermal=(target/'macro'/'dndt_constants.dat').read_bytes()
        self.assertTrue(thermal.startswith(b'Version#3\r\nGlass\tCatalog\t'))
        for line in self.thermal.splitlines()[2:]: self.assertIn(line,thermal)
        self.assertEqual((self.root/'macro'/'CatalogFull.dat').read_bytes(),self.full)
        self.assertEqual((self.root/'macro'/'dndt_constants.dat').read_bytes(),self.thermal)
        self.assertFalse(bundle.verify(target)['ok'])

    def test_apply_backs_up_both_tables_and_verifies_all_four_files(self):
        target=self.work/'bundle'
        bundle.prepare(self.xml,self.root,target)
        result=bundle.apply(target)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'],'files_synced')
        self.assertFalse(result['application_verified'])
        backup=Path(result['backup'])
        self.assertEqual((backup/'macro'/'CatalogFull.dat').read_bytes(),self.full)
        self.assertEqual((backup/'macro'/'dndt_constants.dat').read_bytes(),self.thermal)
        self.assertEqual(len(result['files']),4)
        self.assertTrue(bundle.verify(target)['ok'])

    def test_apply_does_not_install_a_bundle_for_a_different_selected_directory(self):
        target = self.work / 'bundle'
        bundle.prepare(self.xml, self.root, target)
        with self.assertRaises(CatalogError):
            bundle.apply(target, self.work / 'OTHER_CODEV')
        self.assertFalse((self.root / 'glass/CUSTOM.xml').exists())
        self.assertEqual((self.root / 'macro/CatalogFull.dat').read_bytes(), self.full)
        self.assertTrue(bundle.apply(target, self.root)['ok'])

    def test_updating_library_replaces_its_old_rows_without_duplication(self):
        first=self.work/'first'
        bundle.prepare(self.xml,self.root,first)
        bundle.apply(first)
        glass=load_catalog(self.xml).glasses[0]
        smaller=self.work/'smaller.xml'
        export_catalog([glass],smaller,catalog_name='CUSTOM')
        second=self.work/'second'
        result=bundle.prepare(smaller,self.root,second)
        self.assertEqual([c['replaced_catalog_rows'] for c in result['table_changes']],[2,2])
        bundle.apply(second)
        lines=(self.root/'macro'/'CatalogFull.dat').read_text().splitlines()
        self.assertEqual(sum(l.startswith('CUSTOM\t') for l in lines),1)
        thermal=(self.root/'macro'/'dndt_constants.dat').read_text().splitlines()
        self.assertEqual(sum('\tCUSTOM\t' in l for l in thermal),1)

    def test_stale_merged_snapshot_does_not_overwrite_later_changes(self):
        target=self.work/'bundle'
        bundle.prepare(self.xml,self.root,target)
        changed=self.full+b'\r\nOTHER\tNEWGLASS'
        (self.root/'macro'/'CatalogFull.dat').write_bytes(changed)
        with self.assertRaisesRegex(CatalogError,'重新 prepare'):
            bundle.apply(target)
        self.assertEqual((self.root/'macro'/'CatalogFull.dat').read_bytes(),changed)
        self.assertEqual((self.root/'macro'/'dndt_constants.dat').read_bytes(),self.thermal)

    def test_ir_only_material_is_not_added_to_visible_macro_tables(self):
        source=self.work/'IR.AGF'
        source.write_text('NM IR 1 0 1 0 0 0\nCD 4 0 0 0 0 0\nLD 1 10\n')
        xml=self.work/'IR.xml'
        export_catalog(load_catalog(source).glasses,xml)
        with self.assertRaisesRegex(CatalogError,'无有效可见光'):
            bundle.prepare(xml,self.root,self.work/'bundle')
        self.assertFalse((self.work/'bundle').exists())

    def test_equation_codes_match_native_catalog_and_thermal_macro(self):
        source=self.work/'HERZ.AGF'
        source.write_text('NM TESTHRZ 3 0 1.5 50 0 0\nCD 1.5 .001 .0001 0 0 0\nLD .4 1.1\n')
        xml=self.work/'HERZ.xml'
        sellmeier=next(g for g in load_catalog(self.synthetic).glasses if g.formula==2)
        export_catalog([*load_catalog(source).glasses,sellmeier],xml)
        out=self.work/'bundle'
        bundle.prepare(xml,self.root,out)
        rows=(out/'macro'/'dndt_constants.dat').read_text().splitlines()
        generated=next(line for line in rows if line.startswith('TESTHRZ\tHERZ\t'))
        # dndtcalc.seq branches on HRZ, not HERZ, for Herzberger materials.
        self.assertEqual(generated.split('\t')[2].upper(),'HRZ')
        lines=(out/'macro'/'CatalogFull.dat').read_text().splitlines()
        header=lines[0].split('\t')
        code=header.index('Equation_type')
        hrz=next(line for line in lines if line.startswith('HERZ\tTESTHRZ\t'))
        gms=next(line for line in lines if line.startswith('HERZ\tSYNTH_B\t'))
        self.assertEqual(hrz.split('\t')[code],'HRZG')
        self.assertEqual(gms.split('\t')[code],'SSHT')

    def test_uninstall_removes_library_and_rows_with_full_backup(self):
        target=self.work/'bundle'
        bundle.prepare(self.xml,self.root,target)
        bundle.apply(target)
        before={relative:(self.root/relative).read_bytes() for relative in
                ('glass/CUSTOM.xml','macro/custom.dat','macro/CatalogFull.dat','macro/dndt_constants.dat')}
        result=bundle.uninstall('CUSTOM',self.root)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'],'files_removed')
        self.assertEqual([item['removed_catalog_rows'] for item in result['table_changes']],[2,2])
        self.assertFalse((self.root/'glass/CUSTOM.xml').exists())
        self.assertFalse((self.root/'macro/custom.dat').exists())
        self.assertEqual((self.root/'macro/CatalogFull.dat').read_bytes(),self.full)
        self.assertEqual((self.root/'macro/dndt_constants.dat').read_bytes(),self.thermal)
        for relative,data in before.items():
            self.assertEqual((Path(result['backup'])/relative).read_bytes(),data)
        self.assertTrue((Path(result['backup'])/'uninstall-report.json').exists())

    def test_uninstall_keeps_catalog_installed_later(self):
        bundle.prepare(self.xml,self.root,self.work/'first')
        bundle.apply(self.work/'first')
        other=self.work/'OTHER.xml'
        export_catalog(load_catalog(self.xml).glasses,other)
        bundle.prepare(other,self.root,self.work/'second')
        bundle.apply(self.work/'second')
        bundle.uninstall('CUSTOM',self.root)
        self.assertTrue(bundle.verify(self.work/'second')['ok'] is False)  # Its whole-table snapshot still includes CUSTOM.
        self.assertEqual((self.root/'glass/OTHER.xml').read_bytes(),other.read_bytes())
        for filename,needle in (('CatalogFull.dat','OTHER\t'),('dndt_constants.dat','\tOTHER\t')):
            data=(self.root/'macro'/filename).read_text()
            self.assertEqual(sum(needle in line for line in data.splitlines()),2)
            self.assertNotIn('CUSTOM\t',data)

    def test_uninstall_invalid_or_missing_name_leaves_tables_unchanged(self):
        for name in ('../CUSTOM','CatalogFull','MISSING'):
            with self.subTest(name=name),self.assertRaises(CatalogError):
                bundle.uninstall(name,self.root)
        self.assertEqual((self.root/'macro/CatalogFull.dat').read_bytes(),self.full)
        self.assertEqual((self.root/'macro/dndt_constants.dat').read_bytes(),self.thermal)

    def test_uninstall_prepares_both_tables_before_removing_library(self):
        bundle.prepare(self.xml,self.root,self.work/'bundle')
        bundle.apply(self.work/'bundle')
        before=(self.root/'macro/CatalogFull.dat').read_bytes()
        (self.root/'macro/dndt_constants.dat').write_bytes(b'BAD HEADER')
        with self.assertRaises(CatalogError):
            bundle.uninstall('CUSTOM',self.root)
        self.assertTrue((self.root/'glass/CUSTOM.xml').exists())
        self.assertTrue((self.root/'macro/custom.dat').exists())
        self.assertEqual((self.root/'macro/CatalogFull.dat').read_bytes(),before)


if __name__=='__main__':
    unittest.main()
