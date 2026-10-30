"""User locations shared by source launches and the portable Windows release."""

import json
import os
from pathlib import Path
import sys

VERSION = "1.2.0"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
USER_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "GlassCatalog"
SETTINGS_FILE = USER_DIR / "settings.json"
EXPORT_ROOT = (Path.home() / "Documents/玻璃库管理/exports") if getattr(sys, "frozen", False) else APP_DIR / "exports"


def default_settings():
    candidates = sorted(path for path in Path("C:/").glob("CODEV*") if (path / "glass").is_dir())
    return {"codev_root": str(candidates[-1]) if candidates else "",
            "zemax_glasscat": str(Path.home() / "Documents/Zemax/Glasscat")}


def load_settings():
    settings = default_settings()
    if SETTINGS_FILE.is_file():
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    return settings


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
