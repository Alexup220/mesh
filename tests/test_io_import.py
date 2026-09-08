import numpy as np
import pytest
import trimesh

from mesh.io_formats import IMPORT_EXTS, MeshImportError, import_meshes, suggest_unit_scale
from mesh.shapes import shape_geometry


@pytest.fixture
def box_file(tmp_path):
    def make(ext):
        path = tmp_path / f"box{ext}"
        trimesh.creation.box(extents=(10.0, 20.0, 30.0)).export(path)
        return path
    return make


@pytest.mark.parametrize("ext", [".stl", ".obj", ".ply", ".glb", ".off"])
def test_imports_each_common_format(box_file, ext):
    shapes = import_meshes(box_file(ext))
    assert len(shapes) == 1
    assert shapes[0].kind == "imported"
    size = shape_geometry(shapes[0]).bounds[1] - shape_geometry(shapes[0]).bounds[0]
    assert np.allclose(sorted(size), [10.0, 20.0, 30.0], atol=1e-3)


def test_imported_shape_is_named_after_the_file(box_file):
    assert import_meshes(box_file(".stl"))[0].name == "box"


def test_import_splits_disconnected_bodies(tmp_path):
    a = trimesh.creation.box(extents=(5.0, 5.0, 5.0))
    b = trimesh.creation.box(extents=(5.0, 5.0, 5.0))
    b.apply_translation([100.0, 0.0, 0.0])
    path = tmp_path / "two.stl"
    (a + b).export(path)
    assert len(import_meshes(path)) == 2


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(MeshImportError):
        import_meshes(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(MeshImportError):
        import_meshes(tmp_path / "nope.stl")


def test_metre_scale_model_is_flagged():
    tiny = trimesh.creation.box(extents=(0.05, 0.05, 0.05))
    scale, label = suggest_unit_scale(tiny)
    assert scale == 1000.0
    assert label == "metres"


def test_normal_millimetre_model_is_not_flagged():
    assert suggest_unit_scale(trimesh.creation.box(extents=(20.0, 20.0, 20.0))) is None


def test_all_declared_extensions_are_lowercase_with_a_dot():
    assert all(e.startswith(".") and e.islower() for e in IMPORT_EXTS)


def test_corrupt_file_message_uses_no_jargon(tmp_path):
    path = tmp_path / "broken.stl"
    path.write_bytes(b"not actually a valid stl file at all")
    with pytest.raises(MeshImportError) as excinfo:
        import_meshes(path)
    text = str(excinfo.value).lower()
    for word in ("manifold", "boolean", "csg", "vertex", "watertight"):
        assert word not in text
    assert "traceback" not in text
    assert "module" not in text
    assert "exception" not in text


def test_body_count_over_max_falls_back_to_a_single_shape(tmp_path, monkeypatch):
    import mesh.io_formats as io_formats

    monkeypatch.setattr(io_formats, "MAX_BODIES", 2)
    parts = [trimesh.creation.box(extents=(1.0, 1.0, 1.0)) for _ in range(3)]
    for i, part in enumerate(parts):
        part.apply_translation([i * 10.0, 0.0, 0.0])
    combined = trimesh.util.concatenate(parts)
    path = tmp_path / "many.stl"
    combined.export(path)

    shapes = import_meshes(path)
    assert len(shapes) == 1
