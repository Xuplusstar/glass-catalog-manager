"""Prepare/install CODE V XML + macro tables, preserving unrelated catalogs.

Preparation reads the selected CODE V installation and writes a separate bundle.
Application is explicit, backs up existing files, and never drives a CODE V lens.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from glass_catalog import CatalogError, load_catalog, optical_constants


def _n(value, missing="--"):
    return missing if value is None else format(value, ".15g")


def _table(data, name):
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    header_index = 1 if lines and lines[0].startswith("Version#") else 0
    if len(lines) <= header_index:
        raise CatalogError(f"{name} 没有表头")
    headers = lines[header_index].split("\t")
    if "Catalog" not in headers or "Glass" not in headers:
        raise CatalogError(f"{name} 表头缺少 Catalog / Glass")
    return lines, header_index, headers


def _merge(data, catalog_name, rows, filename):
    lines, header_index, headers = _table(data, filename)
    catalog_column = headers.index("Catalog")
    if any(set(row) - set(headers) for row in rows):
        raise CatalogError(f"{filename} 缺少本次导出所需字段，不能自动改变表结构")
    newline = "\r\n" if b"\r\n" in data else "\n"
    original = lines[header_index+1:]
    kept = []
    removed = 0
    for line in original:
        columns = line.split("\t")
        if len(columns) > catalog_column and columns[catalog_column].casefold() == catalog_name.casefold():
            removed += 1
        else:
            kept.append(line)
    additions = ["\t".join(row.get(key, "") for key in headers) for row in rows]
    merged = newline.join([*lines[:header_index+1], *kept, *additions])
    if data.endswith((b"\r", b"\n")):
        merged += newline
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    delta = newline.join([*lines[:header_index+1], *additions])
    return bom + merged.encode("utf-8"), bom + delta.encode("utf-8"), removed


def _glass_rows(glass):
    node = glass.raw_xml
    nd, vd = optical_constants(glass)
    # The visible-spectrum macro tables cannot represent undefined nd / Vd.
    if nd is None or vd is None or nd <= 1 or vd <= 0:
        raise CatalogError(f"{glass.name}: 无有效可见光 nd / Vd，不能写入玻璃专家目录；可单独交付 XML")
    if len(glass.coefficients) < 6 or any(x not in (0, None) for x in glass.coefficients[6:]):
        raise CatalogError(f"{glass.name}: 当前总表生成只覆盖六系数模型")
    if glass.formula not in (1, 2, 3):
        raise CatalogError(f"{glass.name}: 当前总表生成暂不支持 {glass.equation}")
    if any(issue.startswith(("TD ", "CTE ", "LD ", "CD ")) for issue in glass.issues):
        raise CatalogError(f"{glass.name}: 热光或光学记录不能直接写入总表：{'；'.join(glass.issues)}")
    props = {p.findtext("Name"): p.findtext("Value", "--") for p in node.findall("./ManufacturersProperties/Property")}
    fields = {"Catalog": glass.catalog, "Glass": glass.name, "Index": _n(nd), "V-value": _n(vd),
              "NF-NC": _n((nd-1)/vd), "DPF": "0", "Price": node.findtext("DollarSlabPrice", "0"),
              "Avail": _n(glass.availability, "8"), "Bubble": props.get("Bubble", "--"),
              "Stain": props.get("Stain_resist", "--")}
    full = {**fields,
            "Low WL": _n(glass.wavelength_range[0]*1000), "High WL": _n(glass.wavelength_range[1]*1000),
            "Price_gob": node.findtext("DollarStripPrice", "0"), "Specific_grav": _n(glass.density),
            "Manufacture_date": node.findtext("ManufactureDate", "--"),
            "date_received": node.findtext("ReceivedDate", "--"), "date_index_changed": node.findtext("IndexChangedDate", "--"),
            "Equation_type": {"Laurent": "SCHT", "Glass Manufacturer Laurent": "SCH2",
                              "Glass Manufacturer Sellmeier": "SSHT", "Herzberger": "HRZG"}[glass.equation],
            "Replacement": node.findtext("Replacement", "--"),
            "Low_exp_coeff": _n(glass.ed[0]) if glass.ed else "--",
            "High_exp_coeff": _n(glass.ed[1]) if len(glass.ed)>1 else "--"}
    for key in ("Transform_temp", "Knoop", "Poisson", "Young", "Acid_resist", "Acid_resist_powder",
                "Acid_resist_surface", "Rigidity", "Water_resist"):
        full[key] = props.get(key, "--")
    thermal = {"Glass": glass.name, "Catalog": glass.catalog,
               "Formula": "gml" if glass.equation == "Glass Manufacturer Laurent" else {1: "lau", 2: "gms", 3: "hrz"}[glass.formula]}
    for key, value in zip(("A1/B1", "A2/C1", "A3/B2", "A4/C2", "A5/B3", "A6/C3"), glass.coefficients[:6]):
        thermal[key] = _n(value, "")
    for key, value in zip(("D0", "D1", "D2", "E0", "E1", "lambda", "MeasuredTemp"), glass.td):
        thermal[key] = _n(value, "")
    for tag, suffix in (("LowCTE", "al"), ("HighCTE", "ah")):
        block = node.find(tag)
        if block is not None:
            index = 0 if suffix == "al" else 1
            thermal["Alpha_lowT" if index == 0 else "Alpha_highT"] = _n(glass.ed[index]*1e-6, "") if glass.ed[index] is not None else ""
            thermal["Tmin_"+suffix] = block.findtext("LowerTemperatureLimit", "")
            thermal["Tmax_"+suffix] = block.findtext("UpperTemperatureLimit", "")
    return fields, full, thermal


def list_catalogs(codev_root):
    root = Path(codev_root).resolve()
    directory = root / "glass"
    catalogs = []
    for path in sorted(directory.glob("*"), key=lambda p: p.name.casefold()):
        if path.suffix.lower() != ".xml" or not path.is_file():
            continue
        item = {"catalog": path.stem, "path": str(path)}
        try:
            library = load_catalog(path)
            item.update(count=len(library.glasses), issues=sum(bool(g.issues) for g in library.glasses))
        except (OSError, ValueError, ET.ParseError) as exc:
            item.update(count=None, error=str(exc))
        catalogs.append(item)
    return {"ok": True, "codev_root": str(root), "exists": directory.is_dir(),
            "count": len(catalogs), "catalogs": catalogs}


def prepare(xml_file, codev_root, bundle_dir=None):
    source = Path(xml_file).resolve()
    root = Path(codev_root).resolve()
    bundle = (Path(bundle_dir).resolve() if bundle_dir is not None else
              source.with_name(source.stem + "_CODEV安装包_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    if root == bundle or root in bundle.parents:
        raise CatalogError("准备目录须位于 CODE V 安装目录之外")
    if bundle.exists() and any(bundle.iterdir()):
        raise CatalogError("准备目录非空，请选择新的目录")
    catalog = load_catalog(source)
    if catalog.format != "xml":
        raise CatalogError("先转换成最终 CODE V XML，再准备安装包")
    if not catalog.name.isascii() or not catalog.name.replace("_", "").isalnum():
        raise CatalogError("Catalog Name 须为英文、数字或下划线")
    duplicates = [name for name, count in Counter(g.name.casefold() for g in catalog.glasses).items() if count>1]
    if duplicates:
        raise CatalogError("XML 含重复材料名称："+", ".join(duplicates))
    all_rows = [_glass_rows(glass) for glass in catalog.glasses]
    outputs = {f"glass/{catalog.name}.xml": source.read_bytes()}
    changes = []
    for filename, index in (("CatalogFull.dat", 1), ("dndt_constants.dat", 2)):
        original = (root/"macro"/filename).read_bytes()
        merged, delta, removed = _merge(original, catalog.name, [rows[index] for rows in all_rows], filename)
        outputs[f"macro/{filename}"] = merged
        outputs[f"catalog_tables/{Path(filename).stem}_{catalog.name}.dat"] = delta
        changes.append({"file": f"macro/{filename}", "replaced_catalog_rows": removed, "new_catalog_rows": len(all_rows)})
    simple_header = ["Catalog", "Glass", "Index", "V-value", "NF-NC", "DPF", "Price", "Avail", "Bubble", "Stain"]
    outputs[f"macro/{catalog.name.lower()}.dat"] = ("\n".join(["\t".join(simple_header),
        *("\t".join(rows[0][key] for key in simple_header) for rows in all_rows)])).encode("utf-8")
    # Table filenames are reserved; a catalog named CatalogFull would overwrite a master.
    if catalog.name.casefold() in {"catalogfull", "dndt_constants"}:
        raise CatalogError("Catalog Name 与总表文件名冲突，请另取库名")
    files = []
    for relative, data in outputs.items():
        p = bundle/relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if not relative.startswith("catalog_tables/"):
            target = root/relative
            files.append({"file": relative, "sha256": hashlib.sha256(data).hexdigest(),
                          "previous_sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None})
    manifest = {"schema": 1, "catalog": catalog.name, "count": len(catalog.glasses), "source_xml": str(source),
                "codev_root": str(root), "files": files, "table_changes": changes,
                "status": "prepared", "application_verified": False,
                "notes": ["总表沿用本机原表头、Version 行和其他库数据；本库原行由这次 XML 的完整材料集合替换。",
                          "DPF 暂为 0；热光模型、测量温度和单位仍须按转换报告及实际使用需求核验。",
                          "本包是本机目录的合并快照，其他库发生变化后须重新准备。"]}
    (bundle/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"ok": True, "bundle": str(bundle), **manifest}


def _read_bundle(bundle_dir):
    bundle = Path(bundle_dir).resolve()
    if not (bundle/"manifest.json").is_file():
        raise CatalogError(f"所选文件夹不是完整导出包：{bundle}。请选包含 manifest.json、glass 和 macro 的文件夹；"
                           "新材料可直接使用“一键转换并安装到 CODE V”。")
    manifest = json.loads((bundle/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise CatalogError("安装包版本不支持")
    root = Path(manifest["codev_root"]).resolve()
    expected = {f"glass/{manifest['catalog']}.xml", f"macro/{manifest['catalog'].lower()}.dat",
                "macro/CatalogFull.dat", "macro/dndt_constants.dat"}
    if {item["file"] for item in manifest["files"]} != expected:
        raise CatalogError("安装包文件列表与预期不符")
    for item in manifest["files"]:
        source = (bundle/item["file"]).resolve()
        target = (root/item["file"]).resolve()
        if bundle not in source.parents or root not in target.parents:
            raise CatalogError("安装包路径超出指定目录")
        if hashlib.sha256(source.read_bytes()).hexdigest()!=item["sha256"]:
            raise CatalogError(f"准备文件被改变：{item['file']}，请重新准备")
    return bundle, root, manifest


def apply(bundle_dir, codev_root=None):
    bundle, root, manifest = _read_bundle(bundle_dir)
    if codev_root is not None and Path(codev_root).resolve() != root:
        raise CatalogError(f"导出包的安装目标是 {root}，与当前选择的 CODE V 目录不同；请按当前目录重新生成完整包")
    # A staged full master table can otherwise undo another catalog installed since preparation.
    for item in manifest["files"]:
        target = root/item["file"]
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if actual != item["previous_sha256"]:
            raise CatalogError(f"目标文件自准备后发生变化：{item['file']}；重新 prepare 后再安装")
    backup = bundle/("backup-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    for item in manifest["files"]:
        target = root/item["file"]
        if target.exists():
            p = backup/item["file"]
            p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,p)
    for item in manifest["files"]:
        target = root/item["file"]
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(bundle/item["file"],target)
    result = verify(bundle)
    result["backup"] = str(backup)
    (bundle/"install-report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def verify(bundle_dir):
    bundle, root, manifest = _read_bundle(bundle_dir)
    checks=[]
    for item in manifest["files"]:
        target=root/item["file"]
        matches=target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==item["sha256"]
        checks.append({"file":str(target),"matches":matches})
    matched=all(c["matches"] for c in checks)
    return {"ok":matched,"status":"files_synced" if matched else "files_not_synced",
            "catalog":manifest["catalog"],"count":manifest["count"],"bundle":str(bundle),
            "files":checks,"application_verified":False,
            "next":"在 CODE V 中用 GLD / GLI / GPR 查询新库；文件一致尚不代表软件内识别验收通过。"}


def uninstall(catalog_name, codev_root, backup_dir=None):
    """Remove one named catalog from the current files, retaining other catalogs."""
    if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", catalog_name)
            or catalog_name.casefold() in {"catalogfull", "dndt_constants"}):
        raise CatalogError("请选择有效的 CODE V 库名（字母、数字或下划线）")
    root = Path(codev_root).resolve()
    xml_relative = f"glass/{catalog_name}.xml"
    xml_file = root/xml_relative
    if not xml_file.is_file():
        raise CatalogError(f"CODE V 中没有找到 {catalog_name}：{xml_file}")
    xml = ET.fromstring(xml_file.read_bytes())
    if xml.tag != "Catalog" or (xml.findtext("Name") or "").casefold() != catalog_name.casefold():
        raise CatalogError("XML 内部库名与文件名不一致，请先核对要卸载的库")
    catalog_name = xml.findtext("Name")
    outputs = {}
    changes = []
    for filename in ("CatalogFull.dat", "dndt_constants.dat"):
        relative = f"macro/{filename}"
        data, _, removed = _merge((root/relative).read_bytes(), catalog_name, [], filename)
        outputs[relative] = data
        changes.append({"file": relative, "removed_catalog_rows": removed})
    removed_files = [xml_relative]
    simple_relative = f"macro/{catalog_name.lower()}.dat"
    if (root/simple_relative).is_file():
        removed_files.append(simple_relative)
    backup = (Path(backup_dir).resolve() if backup_dir is not None else
              root/"catalog_backups"/("uninstall_"+catalog_name+"_"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
    if backup.exists() and any(backup.iterdir()):
        raise CatalogError("卸载备份目录非空，请选择新目录")
    for relative in [*outputs, *removed_files]:
        target = backup/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/relative, target)
    for relative, data in outputs.items():
        (root/relative).write_bytes(data)
    for relative in removed_files:
        (root/relative).unlink()
    checks = [{"file": str(root/relative), "matches": (root/relative).read_bytes() == data}
              for relative, data in outputs.items()]
    checks += [{"file": str(root/relative), "removed": not (root/relative).exists()} for relative in removed_files]
    matched = all(item.get("matches", item.get("removed")) for item in checks)
    result = {"ok": matched, "status": "files_removed" if matched else "uninstall_incomplete",
              "catalog": catalog_name, "count": len(xml.findall("./Glasses/Glass")), "codev_root": str(root),
              "backup": str(backup), "files": checks, "table_changes": changes, "application_verified": False,
              "next": "在 CODE V 中查询确认该库已移除；已打开的软件可能仍需重新加载。"}
    (backup/"uninstall-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description="准备、安装、卸载并检查 CODE V XML 与两个材料总表")
    sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("list",help="只读列出已安装的 XML 库、材料数量与数据提示")
    p.add_argument("--codev-root",type=Path,required=True)
    p.add_argument("--json",action="store_true")
    p=sub.add_parser("prepare",help="读取本机总表，在独立目录生成合并安装包")
    p.add_argument("xml",type=Path)
    p.add_argument("--codev-root",type=Path,required=True)
    p.add_argument("--bundle",type=Path,help="默认在 XML 旁新建带时间的目录")
    p.add_argument("--json",action="store_true")
    for action in ("apply","verify"):
        p=sub.add_parser(action,help="写入并备份软件文件" if action=="apply" else "只读核对已安装文件")
        p.add_argument("bundle",type=Path)
        p.add_argument("--json",action="store_true")
    p=sub.add_parser("uninstall",help="备份后卸载指定库，并从两张当前总表移除该库条目")
    p.add_argument("catalog",help="CODE V 库名")
    p.add_argument("--codev-root",type=Path,required=True)
    p.add_argument("--backup",type=Path,help="卸载备份目录；默认存到 CODE V 的 catalog_backups 下")
    p.add_argument("--json",action="store_true")
    args=parser.parse_args(argv)
    try:
        if args.action=="list":
            result=list_catalogs(args.codev_root)
        elif args.action=="prepare":
            result=prepare(args.xml,args.codev_root,args.bundle)
        elif args.action=="apply":
            result=apply(args.bundle)
        elif args.action=="uninstall":
            result=uninstall(args.catalog,args.codev_root,args.backup)
        else:
            result=verify(args.bundle)
    except (OSError,ValueError,KeyError,ET.ParseError) as exc:
        result={"ok":False,"error":str(exc)}
    if args.json:
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    else:
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result["ok"] else 2


if __name__=="__main__":
    raise SystemExit(main())
