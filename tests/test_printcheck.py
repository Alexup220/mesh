import numpy as np
import pytest

from mesh.printcheck import check
from mesh.scene import Scene, new_primitive


def cube(size, at=(0.0, 0.0, 0.0)):
    s = new_primitive("cube")
    s.params.update(width=size, depth=size, height=size)
    s.transform[:3, 3] = at
    return s


def test_empty_scene_reports_empty():
    report = check(Scene())
    assert report.empty is True
    assert report.fits is True
    assert "Nothing" in report.message


def test_small_model_fits_and_is_watertight():
    scene = Scene()
    scene.add(cube(20.0))
    report = check(scene)
    assert report.empty is False
    assert report.watertight is True
    assert report.fits is True
    assert np.allclose(report.size_mm, (20.0, 20.0, 20.0), atol=1e-6)
    assert np.isclose(report.volume_mm3, 8000.0, rtol=1e-3)


def test_model_larger_than_the_build_volume_does_not_fit():
    scene = Scene()
    scene.add(cube(400.0))
    report = check(scene)
    assert report.fits is False
    assert "too big" in report.message.lower()


def test_hidden_shapes_are_excluded():
    scene = Scene()
    big = cube(400.0)
    big.visible = False
    scene.add(big)
    scene.add(cube(10.0))
    assert check(scene).fits is True


def test_scene_of_only_holes_is_reported_as_empty():
    scene = Scene()
    hole = cube(10.0)
    hole.is_hole = True
    scene.add(hole)
    assert check(scene).empty is True


def _open_sheet():
    """A two-triangle flat sheet: not watertight, and nothing about it can
    be repaired into a solid -- exactly what makes check() take the "has
    gaps" branch rather than "ready to print"."""
    import trimesh

    verts = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


@pytest.mark.parametrize(
    "build_scene, expected_snippet",
    [
        pytest.param(lambda: Scene(shapes=[cube(20.0)]), "ready", id="ready_to_print"),
        pytest.param(lambda: Scene(shapes=[cube(400.0)]), "too big", id="too_big"),
        pytest.param(lambda: Scene(shapes=[cube(20.0)]), "gaps", id="has_gaps"),
    ],
)
def test_message_uses_no_jargon(monkeypatch, build_scene, expected_snippet):
    """The plain-language rule is a global constraint, not something that
    only needs to hold for the happy path -- this covers all three
    message branches in check(): ready to print, too big, and has gaps."""
    scene = build_scene()

    if expected_snippet == "gaps":
        monkeypatch.setattr("mesh.printcheck.evaluate", lambda shapes: _open_sheet())

    report = check(scene)
    assert expected_snippet in report.message.lower()

    text = report.message.lower()
    for word in ("manifold", "boolean", "csg", "vertex", "watertight"):
        assert word not in text
