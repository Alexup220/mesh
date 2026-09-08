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
