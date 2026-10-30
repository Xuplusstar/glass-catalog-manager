"""Launch the desktop UI using a local Python with PySide6 installed."""

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from release_check import run
        return run(sys.argv[2])
    if find_spec("PySide6") is not None:
        from glass_catalog_ui import main as run_window
        return run_window()
    for interpreter in (Path(__file__).resolve().parent / ".build-venv/Scripts/python.exe",
                        Path.home() / "anaconda3/python.exe"):
        if interpreter.is_file() and interpreter.resolve() != Path(sys.executable).resolve():
            return subprocess.call([str(interpreter), "-X", "utf8", str(Path(__file__).resolve()), *sys.argv[1:]])
    print("窗口需要 PySide6。请先运行：python -m pip install -r requirements-gui.txt")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
