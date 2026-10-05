import ast
import pathlib

import pytest

CORE = ["blobs", "shapes", "scene", "ops", "io_formats", "printcheck", "solids", "hardware", "builders", "text", "settings", "expert", "sketch", "create", "features", "modify", "edges", "patterns", "guides", "construct", "section", "measure", "threads", "parameters", "history", "components", "coils"]
FORBIDDEN = {"PySide6", "vtk", "vtkmodules", "PyQt5", "PyQt6"}
ROOT = pathlib.Path(__file__).resolve().parents[1] / "mesh"


@pytest.mark.parametrize("module", CORE)
def test_core_module_has_no_gui_imports(module):
    path = ROOT / f"{module}.py"
    assert path.exists(), f"{module}.py does not exist yet"
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    assert not (found & FORBIDDEN), f"{module}.py imports GUI code: {found & FORBIDDEN}"
