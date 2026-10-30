"""Skill entry point; reuse the local tool's single implementation."""

import json
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    config_path = Path(__file__).resolve().parents[1]/"config.json"
    config = (json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file()
              else {"tool_root": "../.."})
    if config.get("executable"):
        gui = len(sys.argv) > 1 and sys.argv[1] == "gui"
        executable = config_path.parent / config["gui_executable" if gui else "executable"]
        return subprocess.call([str(executable.resolve()), *sys.argv[2 if gui else 1:]],
                               stdout=sys.stdout, stderr=sys.stderr,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    tool = (config_path.parent / config["tool_root"]).resolve()
    entry = tool / "glass_catalog.py"
    if not entry.is_file():
        print(json.dumps({"ok":False,"error":f"找不到程序 {entry}，请修正 {config_path}"},ensure_ascii=False))
        return 2
    sys.path.insert(0,str(tool))
    sys.argv[0]=str(entry)
    runpy.run_path(str(entry),run_name="__main__")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
