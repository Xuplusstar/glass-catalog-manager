"""CODE V Glass Expert user lists (tab-separated Catalog / Glass references)."""

import hashlib
import json
from pathlib import Path

from glass_catalog import CatalogError, load_catalog


def installed_catalog_paths(codev_root):
    if not codev_root:
        raise CatalogError("请先选择 CODE V 安装目录，再选择已安装的 XML 库")
    directory = Path(codev_root).resolve() / "glass"
    if not directory.is_dir():
        raise CatalogError(f"未找到 CODE V 的 glass 文件夹：{directory}")
    return sorted(directory.glob("*.xml"), key=lambda path: path.name.casefold())


def export_expert_dat(glasses, output, *, catalog_name=None, reference="source", prefix_source=False,
                      codev_root=None, install_codev=False, selection_info=None, bundle_dir=None,
                      write_report=True):
    output = Path(output).resolve()
    if not glasses:
        raise CatalogError("没有可导出的 Glass Expert 候选材料")
    if reference not in {"auto", "source"}:
        raise CatalogError("DAT 只引用已安装的 CODE V 库；新材料请先转换为 XML 并安装，再导出 DAT")
    if any(g.format != "xml" for g in glasses):
        raise CatalogError("DAT 只能从 CODE V 已安装的 XML 库选材；AGF 请先转换为 XML 并安装")
    if prefix_source:
        raise CatalogError("DAT 保留已安装库的原库名和牌号，请取消材料名前缀")
    if install_codev or bundle_dir is not None:
        raise CatalogError("DAT 仅导出候选清单；安装新库请另用 XML 转换安装")
    installed_paths = {str(path.resolve()).casefold(): path for path in installed_catalog_paths(codev_root)}
    sources = {g.source.casefold() for g in glasses}
    external = sources - installed_paths.keys()
    if external:
        raise CatalogError("DAT 只能选择所选 CODE V 的 glass 文件夹中已安装的 XML："
                           + "、".join(Path(path).name for path in sorted(external))
                           + "；请先安装或重新选择已安装库")
    installed = {}
    for source in sources:
        catalog = load_catalog(installed_paths[source])
        installed[source] = {(catalog.name.casefold(), g.name.casefold()): (catalog.name, g.name)
                             for g in catalog.glasses}
    missing = [f"{g.catalog}/{g.name}" for g in glasses
               if (g.catalog.casefold(), g.name.casefold()) not in installed[g.source.casefold()]]
    if missing:
        raise CatalogError("CODE V 已安装库中未找到以下材料：" + "、".join(missing) + "；请重新选择已安装库")
    pairs = [installed[g.source.casefold()][(g.catalog.casefold(), g.name.casefold())] for g in glasses]
    if len(set((c.casefold(), n.casefold()) for c, n in pairs)) != len(pairs):
        raise CatalogError("同一 CODE V 库与材料名重复，请先移除重复输入")
    if any(not item.isascii() or any(char in item for char in "\t\r\n") for pair in pairs for item in pair):
        raise CatalogError("Glass Expert 库名和牌号应为 ASCII，且不能包含制表符或换行")
    data = ("Catalog\tGlass\r\n" + "".join(f"{catalog}\t{name}\r\n" for catalog, name in pairs)).encode("ascii")
    report = {"ok": True, "output": str(output), "catalog": catalog_name or output.stem,
              "format": "glass_expert_dat", "count": len(pairs), "reference_mode": "source",
              "codev_root": str(Path(codev_root).resolve()),
              "reference_catalogs": sorted({catalog for catalog, _ in pairs}),
              "reference_verification": {"checked": True, "missing": []}, "columns": ["Catalog", "Glass"],
              "name_map": [{"source": g.source, "catalog": g.catalog, "original": g.name,
                            "exported_catalog": catalog, "exported": name}
                           for g, (catalog, name) in zip(glasses, pairs)],
              "selection": selection_info or {}, "warnings": [],
              "output_sha256": hashlib.sha256(data).hexdigest()}
    if any(g.supplier_reference for g in glasses):
        from supplier_catalog import reference_report
        report["supplier_data"] = reference_report(glasses)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    if write_report:
        report_path = output.with_suffix(output.suffix + ".report.json")
        report["report"] = str(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report
