"""Hollow out: exact for box / cylinder / sphere, approximate otherwise."""

import numpy as np
import pytest

from mesh.builders import BuildError, hollow, hollows_exactly
from mesh.ops import ungroup
from mesh.scene import DEFAULT_FIT_CLEARANCES, new_primitive, transform_with_euler
from mesh.shapes import shape_geometry

CLEAR = dict(DEFAULT_FIT_CLEARANCES)


def box(w=30.0, d=20.0, h=10.0):
    s = new_primitive("cube")
    s.params.update(width=w, depth=d, height=h)
    return s


def test_box_hollows_exactly():
    g = hollow(box(), 2.0)
    tm = shape_geometry(g)
    assert tm.is_watertight
    assert np.isclose(tm.volume, 6000.0 - 26.0 * 16.0 * 6.0, rtol=1e-6)
    assert np.allclose(tm.bounds, shape_geometry(box()).bounds)


def test_box_with_open_top_and_drain():
    g = hollow(box(), 2.0, open_top=True, drain=3.0)
    tm = shape_geometry(g)
    assert tm.is_watertight
    inside = 26.0 * 16.0 * 8.0
    drain = np.pi * 1.5**2 * 2.0
    assert np.isclose(tm.volume, 6000.0 - inside - drain, rtol=2e-3)


def test_cylinder_hollows_exactly():
    cyl = new_primitive("cylinder")
    cyl.params.update(diameter=20.0, height=30.0)
    tm = shape_geometry(hollow(cyl, 2.0))
    assert tm.is_watertight
    outer = shape_geometry(cyl).volume
    inner_scale = (8.0 / 10.0) ** 2 * (26.0 / 30.0)  # same 64-sided polygon, inset
    assert np.isclose(tm.volume, outer * (1.0 - inner_scale), rtol=1e-6)


def test_sphere_hollows_exactly_and_open_top_makes_a_cup():
    ball = new_primitive("sphere")
    ball.params.update(diameter=40.0)
    closed = shape_geometry(hollow(ball, 3.0))
    outer = shape_geometry(ball).volume
    assert closed.is_watertight
    assert np.isclose(closed.volume, outer * (1.0 - (34.0 / 40.0) ** 3), rtol=1e-6)
    cup = shape_geometry(hollow(ball, 3.0, open_top=True))
    assert cup.is_watertight
    assert cup.volume < closed.volume


def test_turned_part_hollows_around_its_own_axis():
    part = box()
    part.transform = transform_with_euler(part.transform, 30.0, 45.0, 10.0)
    part.transform[:3, 3] = [5.0, -4.0, 12.0]
    tm = shape_geometry(hollow(part, 2.0))
    assert tm.is_watertight
    assert np.isclose(tm.volume, 6000.0 - 26.0 * 16.0 * 6.0, rtol=1e-6)


def test_ungroup_gives_back_the_original():
    part = box()
    pieces = ungroup(hollow(part, 2.0, drain=2.0))
    assert pieces[0].id == part.id and not pieces[0].is_hole
    assert all(p.is_hole for p in pieces[1:])
    assert len(pieces) == 3


@pytest.mark.parametrize("wall, kwargs", [
    (10.0, {}),                     # walls meet across the 20 mm depth
    (5.0, {}),                      # closed: 2 x 5 = height 10
    (2.0, {"drain": 16.0}),         # drain wider than the 16 mm inside
    (0.0, {}),
])
def test_impossible_walls_are_refused(wall, kwargs):
    with pytest.raises(BuildError):
        hollow(box(), wall, **kwargs)


def test_open_top_allows_a_wall_up_to_the_full_height():
    tm = shape_geometry(hollow(box(h=10.0), 5.0, open_top=True))
    assert tm.is_watertight


def test_holes_cannot_be_hollowed():
    part = box()
    part.is_hole = True
    with pytest.raises(BuildError):
        hollow(part, 2.0)


@pytest.mark.parametrize("kind", ["cone", "wedge", "pyramid"])
def test_other_shapes_hollow_approximately_and_watertight(kind):
    part = new_primitive(kind)
    assert not hollows_exactly(part)
    g = hollow(part, 1.5, drain=2.0)
    tm = shape_geometry(g)
    assert tm.is_watertight
    outer = shape_geometry(part)
    assert 0.0 < tm.volume < outer.volume
    assert np.allclose(tm.bounds, outer.bounds, atol=1e-4)


def test_approximate_wall_is_close_to_the_requested_thickness():
    """A wedge's bottom wall is flat, so the cavity floor should sit about
    one wall thickness above the plane."""
    part = new_primitive("wedge")
    pieces = ungroup(hollow(part, 2.0))
    cavity = shape_geometry(pieces[1])
    assert np.isclose(cavity.bounds[0][2], 2.0, atol=0.05)


def test_approximate_open_top_is_refused_plainly():
    with pytest.raises(BuildError, match="Open top"):
        hollow(new_primitive("cone"), 1.0, open_top=True)


def test_approximate_too_thick_is_refused():
    with pytest.raises(BuildError):
        hollow(new_primitive("pyramid"), 15.0)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


@pytest.fixture
def warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    return seen


def test_hollow_in_the_window_is_one_undo_step(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.hollow_selected(2.0) is True
    scene = window.document.scene
    assert len(scene.shapes) == 1 and scene.shapes[0].kind == "group"
    assert scene.selection == [scene.shapes[0].id]
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert window.document.scene.shapes[0].kind == "primitive"


def test_a_too_thick_wall_leaves_no_undo_step(window, warnings):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.hollow_selected(15.0) is False
    assert len(window.document._undo) == depth
    assert window.document.scene.shapes[0].kind == "primitive"
    assert len(warnings) == 1 and "too thick" in warnings[0]


def test_hollow_needs_exactly_one_part(window):
    depth = len(window.document._undo)
    assert window.hollow_selected(2.0) is False
    assert len(window.document._undo) == depth


def test_dialog_says_when_the_result_is_approximate(window, monkeypatch):
    from mesh import panels

    seen = {}

    def fake_run_form(parent, title, fields, note=None):
        seen["keys"] = [f[0] for f in fields]
        seen["note"] = note
        return None

    monkeypatch.setattr(panels, "run_form", fake_run_form)
    window.add_primitive("cone")
    window.do_hollow()
    assert "approximately" in seen["note"]
    assert "open_top" not in seen["keys"]
    window.add_primitive("cube")
    window.do_hollow()
    assert seen["note"] is None
    assert seen["keys"] == ["wall", "open_top", "drain"]
