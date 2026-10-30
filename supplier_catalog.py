"""Read supplier melting-frequency tables without changing optical records."""

from dataclasses import dataclass, replace
import csv
import hashlib
from io import StringIO
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from glass_catalog import CatalogError


GRADES = ("MA", "A", "B", "C", "D")
NAME_HEADERS = {"glass", "glassname", "type", "牌号", "玻璃牌号", "材料名称"}
GRADE_HEADERS = {"meltfrequency", "meltingfrequency", "生产频次", "生产频率", "熔炼频率", "厂家分级"}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class SupplierTable:
    manufacturer: str
    source: str
    sha256: str
    version: str | None
    grades: dict[str, str]

    def summary(self):
        return {"manufacturer": self.manufacturer, "source": self.source, "sha256": self.sha256,
                "version": self.version, "materials": len(self.grades)}


def _glass_key(name):
    return re.sub(r"[\s-]", "", name).upper()


def _xlsx_rows(path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in relations}
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            relation = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = targets[relation]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = []
            for row in ET.fromstring(archive.read(target)).findall("s:sheetData/s:row", NS):
                values = []
                for cell in row:
                    column = 0
                    for letter in re.match(r"[A-Z]+", cell.get("r")).group():
                        column = column * 26 + ord(letter) - ord("A") + 1
                    values.extend([""] * (column - len(values)))
                    value = cell.findtext("s:v", "", NS)
                    if cell.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall("s:is//s:t", NS))
                    values[column - 1] = value
                rows.append(values)
            yield sheet.get("name"), rows


def load_supplier_table(path, manufacturer=None):
    path = Path(path).resolve()
    if not manufacturer:
        known = ("CDGM", "SCHOTT", "OHARA", "HOYA", "HIKARI", "SUMITA", "NHG")
        manufacturer = next((name for name in known if re.match(name + r"(?:\d|[-_. ]|$)", path.stem, re.I)), None)
    if not manufacturer or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", manufacturer):
        raise CatalogError("请填写厂家名称，例如 CDGM；匹配只作用于该厂家的库名")
    manufacturer = manufacturer.upper()
    if path.suffix.lower() == ".xlsx":
        try:
            sheets = list(_xlsx_rows(path))
        except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
            raise CatalogError(f"无法读取厂家 XLSX：{exc}") from exc
    elif path.suffix.lower() in {".csv", ".tsv"}:
        data = path.read_bytes()
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = data.decode("gb18030")
        sheets = [(path.name, list(csv.reader(StringIO(content), delimiter="\t" if path.suffix.lower() == ".tsv" else ",")))]
    else:
        raise CatalogError("厂家表支持 .xlsx、.csv 或 .tsv；旧 .xls 请另存为其中一种")
    grades = {}
    for sheet, rows in sheets:
        header = None
        for index, row in enumerate(rows[:25]):
            keys = [re.sub(r"[\s_-]", "", str(value)).casefold() for value in row]
            names = [i for i, value in enumerate(keys) if value in NAME_HEADERS]
            frequencies = [i for i, value in enumerate(keys) if value in GRADE_HEADERS]
            if names and frequencies:
                header = (index, names[0], frequencies[0])
                break
        if header is None:
            continue
        index, name_column, grade_column = header
        for number, row in enumerate(rows[index + 1:], index + 2):
            if len(row) <= max(name_column, grade_column):
                continue
            name, grade = str(row[name_column]).strip(), str(row[grade_column]).strip().upper()
            if not name or not grade:
                continue
            if grade not in GRADES:
                raise CatalogError(f"{sheet} 第 {number} 行的厂家分级 {grade!r} 不在 MA/A/B/C/D 中")
            key = _glass_key(name)
            if key in grades and grades[key] != grade:
                raise CatalogError(f"厂家表同一牌号 {name} 的分级冲突：{grades[key]} / {grade}")
            grades[key] = grade
    if not grades:
        raise CatalogError("厂家表未找到有效材料；表头需含 Glass/牌号 和 Melt Frequency/生产频率 两列")
    version = re.search(r"20\d{2}(?:0[1-9]|1[0-2])", path.stem)
    return SupplierTable(manufacturer, str(path), hashlib.sha256(path.read_bytes()).hexdigest(),
                         version.group() if version else None, grades)


def enrich_glasses(glasses, table):
    reference = table.summary()
    prefix = re.compile(re.escape(table.manufacturer) + r"(?:\d|[-_. ]|$)", re.I)
    result = []
    for glass in glasses:
        grade = table.grades.get(_glass_key(glass.name)) if prefix.match(glass.catalog) else None
        result.append(replace(glass, supplier_grade=grade, supplier_reference=reference if grade else None))
    return result


def reference_report(glasses):
    references = {g.supplier_reference["sha256"]: g.supplier_reference for g in glasses if g.supplier_reference}
    return {"references": list(references.values()),
            "materials": [{"catalog": g.catalog, "name": g.name, "grade": g.supplier_grade,
                           "reference_sha256": g.supplier_reference["sha256"]} for g in glasses if g.supplier_grade]}
