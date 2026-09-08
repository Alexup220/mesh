import json

import numpy as np
import pytest
import trimesh

from mesh.io_formats import (
    EXPORT_EXTS,
    ExportError,
    export_scene,
    load_project,
    save_project,
)
from mesh.scene import Scene, new_primitive


def cube(size=10.0, at=(0.0, 0.0, 0.0), hole=False):
    s = new_primitive("cube")
    s.params.update(width=size, depth=size, height=size)
    s.transform[:3, 3] = at
    s.is_hole = hole
    return s


@pytest.mark.parametrize("ext", EXPORT_EXTS)
def test_exports_each_format(tmp_path, ext):
    scene = Scene()
    scene.add(cube(20.0))
    path = tmp_path / f"part{ext}"
    export_scene(scene, path)
    assert path.exists() and path.stat().st_size > 0


def test_exported_stl_has_the_right_volume(tmp_path):
    scene = Scene()
    scene.add(cube(10.0))
    scene.add(cube(4.0, at=(0.0, 0.0, 2.0), hole=True))
    path = tmp_path / "part.stl"
    export_scene(scene, path)
    assert np.isclose(trimesh.load(path).volume, 936.0, rtol=1e-3)


def test_exporting_an_empty_scene_raises(tmp_path):
    with pytest.raises(ExportError):
        export_scene(Scene(), tmp_path / "part.stl")


def test_exporting_an_unsupported_format_raises(tmp_path):
    scene = Scene()
    scene.add(cube())
    with pytest.raises(ExportError):
        export_scene(scene, tmp_path / "part.dwg")


def test_project_roundtrip_preserves_shapes(tmp_path):
    scene = Scene()
    solid = cube(10.0)
    hole = cube(4.0, hole=True)
    scene.add(solid)
    scene.add(hole)
    scene.build_volume = (150.0, 150.0, 150.0)

    path = tmp_path / "part.mesh"
    save_project(scene, path)
    restored = load_project(path)

    assert [s.id for s in restored.shapes] == [solid.id, hole.id]
    assert restored.shapes[1].is_hole is True
    assert restored.build_volume == (150.0, 150.0, 150.0)
    assert np.allclose(restored.shapes[0].transform, solid.transform)


def test_project_file_records_a_format_version(tmp_path):
    path = tmp_path / "part.mesh"
    save_project(Scene(), path)
    assert json.loads(path.read_text())["format_version"] == 1


def test_project_roundtrip_preserves_imported_geometry(tmp_path):
    source = tmp_path / "box.stl"
    trimesh.creation.box(extents=(6.0, 6.0, 6.0)).export(source)

    from mesh.io_formats import import_meshes
    from mesh.shapes import shape_geometry

    scene = Scene()
    for shape in import_meshes(source):
        scene.add(shape)

    path = tmp_path / "part.mesh"
    save_project(scene, path)
    restored = load_project(path)
    assert np.isclose(shape_geometry(restored.shapes[0]).volume, 216.0, rtol=1e-3)


def test_loading_a_non_project_file_raises(tmp_path):
    path = tmp_path / "junk.mesh"
    path.write_text("not json")
    with pytest.raises(ExportError):
        load_project(path)


def _open_sheet() -> trimesh.Trimesh:
    """A two-triangle flat sheet: not watertight, and fill_holes() cannot
    close it into a solid because it has no boundary loop to cap — it is
    an open surface, not a solid with a hole."""
    verts = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _box_missing_one_triangle() -> trimesh.Trimesh:
    """A closed box with a single triangle removed: not watertight as
    given, but the one missing triangle leaves a single closable boundary
    loop, so fill_holes() + update_faces(nondegenerate_faces()) +
    merge_vertices() can repair it into a solid again."""
    box = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    keep = np.ones(len(box.faces), dtype=bool)
    keep[0] = False
    return trimesh.Trimesh(vertices=box.vertices.copy(), faces=box.faces[keep], process=False)


def test_export_refuses_an_unrepairable_open_mesh(tmp_path, monkeypatch):
    import mesh.ops

    monkeypatch.setattr(mesh.ops, "evaluate", lambda shapes: _open_sheet())

    scene = Scene()
    scene.add(cube())
    path = tmp_path / "part.stl"

    with pytest.raises(ExportError) as excinfo:
        export_scene(scene, path)

    # The refusal must happen before any bytes are written.
    assert not path.exists()

    message = str(excinfo.value).lower()
    for jargon in ("boolean", "csg", "manifold", "vertex"):
        assert jargon not in message
    # No raw library exception text should leak into the dialog.
    assert "trimesh" not in message


def test_export_repairs_a_mesh_with_one_missing_triangle(tmp_path, monkeypatch):
    import mesh.ops

    monkeypatch.setattr(mesh.ops, "evaluate", lambda shapes: _box_missing_one_triangle())

    scene = Scene()
    scene.add(cube())
    path = tmp_path / "part.stl"

    export_scene(scene, path)

    assert path.exists() and path.stat().st_size > 0
    reloaded = trimesh.load(path)
    assert reloaded.is_watertight
    assert np.isclose(reloaded.volume, 64.0, rtol=1e-3)
