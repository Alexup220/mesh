"""Core modules stay free of GUI code, including through what they import.

tests/test_purity.py reads each core module's own import lines. This runs
the imports for real, in a fresh interpreter, and checks that none of
them pulls in Qt or VTK on the way.
"""

import subprocess
import sys

from test_purity import CORE, FORBIDDEN


def test_importing_every_core_module_loads_no_gui_code():
    code = (
        "import importlib, sys\n"
        f"for name in {CORE!r}:\n"
        "    importlib.import_module('mesh.' + name)\n"
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & set({sorted(FORBIDDEN)!r})))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
