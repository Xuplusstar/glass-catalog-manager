"""Build the shareable Windows folder and ZIP from the common source tree."""

import argparse
from datetime import datetime
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from app_settings import VERSION

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ["glass_catalog.py", "glass_catalog_gui.py", "glass_catalog_ui.py", "glass_catalog_ui.qss",
                "codev_catalog_bundle.py", "zemax_catalog_manager.py", "glass_expert.py", "supplier_catalog.py", "app_settings.py",
                "cli_entry.py", "release_check.py", "verify_release.py", "requirements-gui.txt", "requirements-build.txt",
                "build_release.py", "README.md", "使用说明.txt", "AGENTS.md", "LICENSE"]


def main():
    parser = argparse.ArgumentParser(description="构建无需另装 Python 的 Windows 玻璃库管理软件与 AI 命令行")
    default_skill = ROOT / "skill/glass-catalog"
    if not default_skill.is_dir():
        default_skill = ROOT.parent / "skill/glass-catalog"
    parser.add_argument("--skill", type=Path, default=default_skill)
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    release_name = f"GlassCatalog-{VERSION}-Windows-x64"
    destination = args.output.resolve() / "GlassCatalog"
    # PNG frames in a Windows ICO keep the small shortcut sizes crisp at each display scale.
    renderer = QSvgRenderer(str(ROOT / "assets/app.svg"))
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    entries, frames = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        frame = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(0)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        frame.save(buffer, "PNG")
        png = bytes(buffer.data())
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        frames.append(png)
        offset += len(png)
    (ROOT / "assets/app.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(frames))
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    log_path = build / "build-release.log"
    with log_path.open("w", encoding="utf-8") as log:
        common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
                  "--distpath", str(args.output.resolve()), "--specpath", str(build),
                  "--workpath", str(build / "pyinstaller")]
        commands = [
            [*common, "--name", "GlassCatalog", "--windowed", "--onedir",
             "--icon", str(ROOT / "assets/app.ico"),
             "--add-data", f"{ROOT / 'glass_catalog_ui.qss'};.",
             "--add-data", f"{ROOT / 'assets'};assets", str(ROOT / "glass_catalog_gui.py")],
            [*common, "--name", "GlassCatalogCLI", "--console", "--onefile",
             "--distpath", str(destination), "--exclude-module", "PySide6", "--exclude-module", "shiboken6",
             "--exclude-module", "glass_catalog_ui", "--exclude-module", "glass_catalog_gui",
             "--exclude-module", "release_check", str(ROOT / "cli_entry.py")],
        ]
        for command in commands:
            print("构建：" + command[command.index("--name") + 1], flush=True)
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    engine = destination / "source"
    engine.mkdir(exist_ok=True)
    for filename in SOURCE_FILES:
        shutil.copy2(ROOT / filename, engine / filename)
    shutil.copytree(ROOT / "assets", engine / "assets", dirs_exist_ok=True)
    shutil.copytree(ROOT / "tests", engine / "tests", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    skill = destination / "skill/glass-catalog"
    shutil.copytree(args.skill, skill, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    config = {"executable": "../../GlassCatalogCLI.exe", "gui_executable": "../../GlassCatalog.exe",
              "codev_root": "", "zemax_glasscat": ""}
    (skill / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "使用说明.txt", destination / "先读我-使用说明.txt")
    shutil.copy2(ROOT / "README.md", destination / "详细说明.md")
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE")
    licenses = destination / "licenses"
    licenses.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE_PYTHON.txt"
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
    shutil.copy2(python_license, licenses / "Python.txt")
    for package in ("PySide6-Essentials", "shiboken6", "PyInstaller"):
        distribution = metadata.distribution(package)
        for entry in distribution.files or []:
            if "license" in entry.name.casefold() or "copying" in entry.name.casefold():
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = licenses / package / str(entry).split(".dist-info/")[-1]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (licenses / "THIRD_PARTY.txt").write_text(
        "Application source: MIT (see ../LICENSE). Dependencies retain their own licenses.\n"
        "Python: https://www.python.org/ (PSF License)\n"
        "Qt / PySide6 / Shiboken6 6.9.2: https://code.qt.io/pyside/pyside-setup.git/tag/?h=v6.9.2 (LGPLv3 / GPLv3)\n"
        "Qt sources: https://download.qt.io/archive/qt/6.9/6.9.2/single/\n"
        "PyInstaller: https://pyinstaller.org/ (GPL with bootloader exception)\n"
        "Qt libraries remain dynamically linked in _internal and can be replaced.\n"
        "Application source is included in source/. No Zemax or CODE V catalogs are included.\n", encoding="utf-8")
    files = [{"file": path.relative_to(destination).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "bytes": path.stat().st_size} for path in sorted(destination.rglob("*")) if path.is_file()]
    manifest = {"version": VERSION, "platform": "Windows x64", "created": datetime.now().isoformat(),
                "python": sys.version, "files": files}
    (destination / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = args.output.resolve() / (release_name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in destination.rglob("*"):
            if path.is_file():
                output.write(path, destination.name + "/" + path.relative_to(destination).as_posix())
    print(json.dumps({"ok": True, "folder": str(destination), "zip": str(archive),
                      "zip_bytes": archive.stat().st_size, "build_log": str(log_path)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
