"""Validate a relocated share ZIP using only its own executables and resources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "archive": str(args.archive.resolve()), "checks": []}
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(("PYTHON", "CONDA", "QT_")) or name == "VIRTUAL_ENV":
            env.pop(name)
    env["PATH"] = str(Path(env["WINDIR"]) / "System32")
    with tempfile.TemporaryDirectory(prefix="玻璃库分享测试_") as directory:
        work = Path(directory)
        with zipfile.ZipFile(args.archive) as archive:
            assert archive.testzip() is None
            archive.extractall(work / "异地解压")
        package, = (work / "异地解压").iterdir()
        manifest = json.loads((package / "release-manifest.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            assert hashlib.sha256((package / item["file"]).read_bytes()).hexdigest() == item["sha256"], item["file"]
        assert {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()} == {
            "release-manifest.json", *(item["file"] for item in manifest["files"])}
        config = json.loads((package / "skill/glass-catalog/config.json").read_text(encoding="utf-8"))
        assert config["executable"] == "../../GlassCatalogCLI.exe"
        assert not config["codev_root"] and not config["zemax_glasscat"]
        developer_name = Path.home().name.casefold()
        for path in [*package.glob("*.md"), *package.glob("*.txt"), *package.glob("source/*.py"),
                     *package.glob("skill/glass-catalog/**/*.md")]:
            assert developer_name not in path.read_text(encoding="utf-8-sig").casefold(), path
        result["checks"].append({"check": "ZIP 移至中文临时路径、完整性与无开发机路径", "files": len(manifest["files"]), "ok": True})
        gui_report = work / "runtime.json"
        gui = subprocess.run([str(package / "GlassCatalog.exe"), "--self-check", str(gui_report)],
                             env=env, cwd=work, capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        assert gui.returncode == 0, (gui.returncode, gui.stderr)
        runtime = json.loads(gui_report.read_text(encoding="utf-8"))
        assert runtime["ok"] and runtime["frozen"], runtime
        result["gui_runtime"] = runtime
        args.report.with_suffix(".png").write_bytes(gui_report.with_suffix(".png").read_bytes())
        args.report.with_name(args.report.stem + "_DAT.png").write_bytes(gui_report.with_name(gui_report.stem + "_DAT.png").read_bytes())
        args.report.with_name(args.report.stem + "_DAT_small.png").write_bytes(gui_report.with_name(gui_report.stem + "_DAT_small.png").read_bytes())
        record = "NM TEST 1 0 1.5 50 0 0 1\nCD 2.25 0 .008 0 0 0\nLD .3 2.5\nIT .5 .8 5\nIT .6 1 5\n"
        source = work / "CDGM202509.AGF"
        source.write_text(record, encoding="utf-8")
        glasscat = work / "Zemax 材料目录"
        codev = work / "CODE V 安装位置"
        (codev / "glass").mkdir(parents=True)
        installed_xml = codev / "glass/CUSTOM.xml"
        commands = [
            (["inspect", str(source), "--supply-status", "agf:0", "agf:1", "--melt-frequency", "1", "2", "3", "--it-at-nm", "550", "--it-thickness-mm", "10", "--it-min", "80"], 1),
            (["convert", str(source), "--output", str(work / "CUSTOM.AGF")], 1),
            (["convert", str(source), "--output", str(installed_xml)], 1),
            (["inspect", str(installed_xml), "--supply-status", "codev:1"], 1),
            (["convert", str(installed_xml), "--output", str(work / "CANDIDATES.dat"), "--codev-root", str(codev)], 1),
            (["convert", str(installed_xml), "--output", str(work / "REVERSE.AGF")], 1),
            (["zemax", "install", str(work / "CUSTOM.AGF"), "--glasscat", str(glasscat)], 1),
            (["zemax", "list", "--glasscat", str(glasscat)], 1),
            (["zemax", "backup", "CUSTOM", "--glasscat", str(glasscat)], 1),
            (["zemax", "uninstall", "CUSTOM", "--glasscat", str(glasscat)], None),
        ]
        for command, count in commands:
            run = subprocess.run([str(package / "GlassCatalogCLI.exe"), *command, "--json"], env=env, cwd=work,
                                 capture_output=True, encoding="utf-8", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            assert run.returncode == 0, (command, run.stdout, run.stderr)
            data = json.loads(run.stdout)
            assert data["ok"]
            if count is not None:
                assert data.get("count", data.get("selected")) == count, data
            if command[0] == "inspect" and "--it-at-nm" in command:
                assert abs(data["glasses"][0]["filter_internal_transmission_percent"] - 81) < 1e-10
                assert data["glasses"][0]["melt_frequency"] == 1
            elif command[0] == "inspect":
                assert data["glasses"][0]["supply_status"] == "codev:1"
            result["checks"].append({"command": command[:2] if command[0] == "zemax" else command[:1], "ok": True})
        assert (work / "CANDIDATES.dat").read_bytes() == b"Catalog\tGlass\r\nCUSTOM\tTEST\r\n"
        assert not (work / "CANDIDATES.xml").exists()
        supplier_table = work / "CDGM202509.csv"
        supplier_table.write_text("Glass,Melt Frequency\nTEST,MA\n", encoding="utf-8")
        for command in (["inspect", str(source), "--supplier-table", str(supplier_table), "--supplier-grade", "MA"],
                        ["convert", str(source), "--output", str(work / "GRADED.xml"),
                         "--supplier-table", str(supplier_table), "--supplier-grade", "MA"]):
            run = subprocess.run([str(package / "GlassCatalogCLI.exe"), *command, "--json"], env=env, cwd=work,
                                 capture_output=True, encoding="utf-8", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            assert run.returncode == 0, (run.stdout, run.stderr)
            data = json.loads(run.stdout)
            if command[0] == "inspect":
                assert data["selected"] == 1 and data["glasses"][0]["supplier_grade"] == "MA", data
            else:
                assert data["supplier_data"]["materials"][0]["grade"] == "MA", data
            result["checks"].append({"check": "独立 CLI 厂家分级 " + command[0], "ok": True})
        invalid_dat = work / "INVALID.dat"
        bad = subprocess.run([str(package / "GlassCatalogCLI.exe"), "convert", str(source), "--output", str(invalid_dat),
                              "--codev-root", str(codev), "--json"], env=env, cwd=work, capture_output=True,
                             encoding="utf-8", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert bad.returncode == 2 and not json.loads(bad.stdout)["ok"] and not invalid_dat.exists(), bad.stdout
        result["checks"].append({"check": "DAT 拒绝 AGF 且不生成配套 XML", "ok": True})
        wrapper = package / "skill/glass-catalog/scripts/glass_catalog.py"
        run = subprocess.run([sys.executable, "-X", "utf8", str(wrapper), "inspect", str(source), "--json"],
                             env=env, cwd=work, capture_output=True, encoding="utf-8", timeout=30,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode == 0 and json.loads(run.stdout)["selected"] == 1, (run.stdout, run.stderr)
        result["checks"].append({"check": "分享版 skill 相对路径与隐藏窗口 JSON 返回", "ok": True})
        bad = subprocess.run([str(package / "GlassCatalogCLI.exe"), "inspect", str(source), "--it-min", "95", "--json"],
                             env=env, cwd=work, capture_output=True, encoding="utf-8", timeout=30,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        assert bad.returncode == 2 and not json.loads(bad.stdout)["ok"], bad.stdout
        result["checks"].append({"check": "不完整条件返回 JSON 失败及退出码 2", "ok": True})
        result.update(ok=True, version=manifest["version"], python_removed_from_child_path=True,
                      zip_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest())
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "checks": len(result["checks"]) + len(result["gui_runtime"]["checks"]),
                      "report": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
