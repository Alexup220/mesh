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


# --- review fixes -----------------------------------------------------------


def _floor_and_top_area(tm, height: float) -> tuple[float, float]:
    """Material area 1 mm above the bottom and 1 mm below the top."""
    from mesh.solids import to_manifold

    solid = to_manifold(tm)
    return solid.slice(1.0).area(), solid.slice(height - 1.0).area()


@pytest.mark.parametrize("kind", ["rounded_box", "rounded_cylinder", "tube"])
def test_rounded_and_ring_shapes_hollow_into_a_closed_part(kind):
    # These used to come back with a cavity that stopped being a closed
    # solid once stored in the project, and Group / the status bar crashed.
    shape = new_primitive(kind)
    group = hollow(shape, 0.5 if kind == "tube" else 2.0, clearances=DEFAULT_FIT_CLEARANCES)
    tm = shape_geometry(group)
    assert tm.is_volume
    assert 0.0 < tm.volume < shape_geometry(shape).volume


@pytest.mark.parametrize("kind", ["cube", "cylinder"])
@pytest.mark.parametrize("chamfer, wall", [(2.5, 1.0), (3.0, 1.2), (5.0, 2.0)])
def test_hollowing_a_bevelled_part_keeps_the_floor_attached(kind, chamfer, wall):
    shape = new_primitive(kind)
    shape.params["chamfer"] = chamfer
    tm = shape_geometry(hollow(shape, wall))
    assert tm.is_volume
    # A closed hollow part has two surfaces, outside and inside; the
    # inside one faces inward (negative volume). A loose floor would be a
    # second outward-facing piece.
    pieces = [b for b in tm.split(only_watertight=False) if b.volume > 1e-3]
    assert len(pieces) == 1


def test_a_bevel_too_big_for_the_wall_is_refused():
    shape = new_primitive("cube")
    shape.params["chamfer"] = 9.9
    with pytest.raises(BuildError, match="bevel"):
        hollow(shape, 2.0)


@pytest.mark.parametrize("turned", [False, True])
def test_open_top_and_drain_go_through_the_world_top_and_bottom(turned):
    shape = new_primitive("cube")
    if turned:
        # Lay Flat on the top face turns the part over; it looks the same.
        shape.transform = transform_with_euler(shape.transform, 180.0, 0.0, 0.0)
        shape.transform[2, 3] = 20.0
    tm = shape_geometry(hollow(shape, 2.0, open_top=True, drain=4.0))
    floor, top = _floor_and_top_area(tm, 20.0)
    full, ring = 400.0, 400.0 - 16.0 * 16.0
    assert floor == pytest.approx(full - np.pi * 2.0**2, rel=0.02)
    assert top == pytest.approx(ring, rel=1e-6)


def test_open_top_on_a_part_lying_on_its_side_is_refused():
    shape = new_primitive("cylinder")
    shape.transform = transform_with_euler(shape.transform, 90.0, 0.0, 0.0)
    with pytest.raises(BuildError, match="upright"):
        hollow(shape, 2.0, open_top=True)
    # Without open top or a drain, which way it lies doesn't matter.
    assert shape_geometry(hollow(shape, 2.0)).is_volume


def test_approximate_drain_wider_than_the_inside_is_refused():
    with pytest.raises(BuildError, match="drain hole is wider"):
        hollow(new_primitive("cone"), 2.0, drain=30.0)


def test_hollow_of_a_rounded_box_in_the_window_works(window, warnings):
    window.add_primitive("rounded_box")
    assert window.hollow_selected(2.0) is True
    assert warnings == []
    window.do_select_all()
    assert "ready to print" in window.statusBar().currentMessage()


def test_a_turned_ball_opens_at_the_world_top():
    ball = new_primitive("sphere")
    ball.transform = transform_with_euler(ball.transform, 90.0, 0.0, 0.0)
    ball.transform[:3, 3] = (0.0, 10.0, 10.0)  # same centre, now lying on its side
    tm = shape_geometry(hollow(ball, 2.0, open_top=True))
    assert tm.is_volume
    floor, top = _floor_and_top_area(tm, 20.0)
    # 1 mm from either pole the ball is a disc about 59.7 mm2 across: the
    # bottom one is still there, the top one has been cut away.
    assert floor == pytest.approx(np.pi * 19.0, rel=0.05)  # a faceted ball
    assert top == pytest.approx(0.0, abs=1e-6)
