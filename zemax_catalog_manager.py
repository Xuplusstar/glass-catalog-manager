"""Manage Zemax AGF files and their generated BGF caches without driving Zemax."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from glass_catalog import CatalogError, load_catalog


def _catalog_path(glasscat, name):
    if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.rstrip(" .") != name or name in {".", ".."}:
        raise CatalogError("Zemax 库名应为有效文件名，不能包含目录或扩展名")
    return Path(glasscat).resolve() / (name + ".AGF")


def list_catalogs(glasscat):
    root = Path(glasscat).resolve()
    catalogs = []
    for path in sorted(root.glob("*"), key=lambda p: p.name.casefold()):
        if path.suffix.lower() != ".agf" or not path.is_file():
            continue
        item = {"catalog": path.stem, "path": str(path), "bytes": path.stat().st_size,
                "bgf_cache": path.with_suffix(".BGF").exists()}
        try:
            library = load_catalog(path)
            item.update(count=len(library.glasses), encoding=library.encoding,
                        issues=sum(bool(g.issues) for g in library.glasses))
        except (OSError, ValueError) as exc:
            item.update(count=None, error=str(exc))
        catalogs.append(item)
    return {"ok": True, "glasscat": str(root), "exists": root.is_dir(), "count": len(catalogs), "catalogs": catalogs}


def _backup(root, name, action):
    directory = root / "catalog_backups" / (action + "_" + name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    directory.mkdir(parents=True)
    files = []
    for suffix in (".AGF", ".BGF"):
        path = root / (name + suffix)
        if path.exists():
            shutil.copy2(path, directory / path.name)
            files.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"schema": 1, "catalog": name, "glasscat": str(root), "action": action, "files": files}
    (directory / "backup.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory


def backup_catalog(name, glasscat):
    path = _catalog_path(glasscat, name)
    catalog = load_catalog(path)
    directory = _backup(path.parent, name, "backup")
    return {"ok": True, "catalog": name, "count": len(catalog.glasses), "backup": str(directory), "status": "backed_up"}


def install(source, glasscat, catalog_name=None):
    source = Path(source).resolve()
    catalog = load_catalog(source)
    if catalog.format != "agf":
        raise CatalogError("Zemax 安装入口需要 AGF；请先将 CODE V XML 转为 AGF")
    name = catalog_name or source.stem
    target = _catalog_path(glasscat, name)
    if source == target:
        raise CatalogError("该 AGF 已位于目标 Glasscat 目录，可直接载入工作区查看")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup(target.parent, name, "install")
    shutil.copy2(source, target)
    cache = target.with_suffix(".BGF")
    if cache.exists():
        cache.unlink()
    result = {"ok": target.read_bytes() == source.read_bytes(), "catalog": name,
              "count": len(catalog.glasses), "path": str(target), "backup": str(backup),
              "status": "file_installed", "application_verified": False,
              "bgf_policy": "旧 BGF 已备份并移除；由 Zemax 自动生成缓存",
              "note": "在 Zemax 的 System Explorer → Material Catalogs 加入本库，并查询材料确认识别。"}
    (backup / "install-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def uninstall(name, glasscat):
    target = _catalog_path(glasscat, name)
    if not target.is_file():
        raise CatalogError(f"目标 Glasscat 中未找到 {name}.AGF")
    backup = _backup(target.parent, name, "uninstall")
    removed = []
    for path in (target, target.with_suffix(".BGF")):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    result = {"ok": True, "catalog": name, "status": "files_removed", "backup": str(backup),
              "removed": removed, "application_verified": False}
    (backup / "uninstall-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def restore(backup_dir, glasscat):
    directory = Path(backup_dir).resolve()
    manifest = json.loads((directory / "backup.json").read_text(encoding="utf-8"))
    name = manifest["catalog"]
    source = _catalog_path(directory, name)
    entries = {item["file"]: item["sha256"] for item in manifest["files"]}
    if source.name not in entries or hashlib.sha256(source.read_bytes()).hexdigest() != entries[source.name]:
        raise CatalogError("备份中的 AGF 不存在或已改变，请选择完整备份")
    result = install(source, glasscat, name)
    result["status"] = "file_restored"
    result["restored_from"] = str(directory)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Zemax Glasscat 查看、安装、备份、卸载与恢复")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "install", "backup", "uninstall", "restore"):
        item = sub.add_parser(command)
        item.add_argument("--glasscat", type=Path, required=True, help="Zemax 实际使用的 Glasscat 目录")
        item.add_argument("--json", action="store_true")
        if command == "install":
            item.add_argument("source", type=Path)
            item.add_argument("--catalog-name")
        elif command == "restore":
            item.add_argument("backup_dir", type=Path)
        elif command in {"backup", "uninstall"}:
            item.add_argument("catalog")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = list_catalogs(args.glasscat)
        elif args.command == "install":
            result = install(args.source, args.glasscat, args.catalog_name)
        elif args.command == "restore":
            result = restore(args.backup_dir, args.glasscat)
        else:
            result = (backup_catalog if args.command == "backup" else uninstall)(args.catalog, args.glasscat)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False) if args.json else
              (f"已找到 {result['count']} 个库" if args.command == "list" else
               f"{result['catalog']}: {result['status']}\n备份：{result['backup']}"))
        return 0 if result["ok"] else 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False) if args.json else str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
