"""Console executable entry; the same core used by the desktop window."""

import sys
from pathlib import Path
import subprocess
from glass_catalog import main

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if getattr(sys, "frozen", False) and len(sys.argv) > 1 and sys.argv[1] == "gui":
        subprocess.Popen([str(Path(sys.executable).with_name("GlassCatalog.exe")), *sys.argv[2:]],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        raise SystemExit(0)
    raise SystemExit(main())
