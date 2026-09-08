import numpy as np

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


def test_message_uses_no_jargon():
    scene = Scene()
    scene.add(cube(20.0))
    text = check(scene).message.lower()
    for word in ("manifold", "boolean", "csg", "vertex", "watertight"):
        assert word not in text
