"""Split part: two watertight halves, cut faces down, optional pegs."""

import numpy as np
import pytest

from mesh.builders import BuildError, split
from mesh.ops import ungroup
from mesh.scene import DEFAULT_FIT_CLEARANCES, new_primitive
from mesh.shapes import shape_geometry

CLEAR = dict(DEFAULT_FIT_CLEARANCES)


def block(w=40.0, d=30.0, h=20.0):
    s = new_primitive("cube")
    s.params.update(width=w, depth=d, height=h)
    return s


def down_area(tm):
    down = tm.face_normals[:, 2] < -0.999
    return float(tm.area_faces[down].sum())


@pytest.mark.parametrize("axis, position, volumes, cut_area", [
    ("z", 5.0, (6000.0, 18000.0), 1200.0),     # 40 x 30 cut face
    ("x", 10.0, (18000.0, 6000.0), 600.0),     # 30 x 20 cut face
    ("y", -5.0, (8000.0, 16000.0), 800.0),     # 40 x 20 cut face
])
def test_halves_are_watertight_and_rest_on_their_cut_faces(axis, position, volumes, cut_area):
    first, second = split(block(), axis, position, clearances=CLEAR)
    for part, volume in zip((first, second), volumes):
        tm = shape_geometry(part)
        assert tm.is_watertight
        assert np.isclose(tm.volume, volume, rtol=1e-6)
        assert np.isclose(tm.bounds[0][2], 0.0, atol=1e-6)
        # Lying on the cut face: the face on the bed is the cut's size.
        assert np.isclose(down_area(tm), cut_area, rtol=1e-6)


def test_halves_sit_side_by_side_without_touching():
    first, second = split(block(), "z", 10.0, clearances=CLEAR)
    a, b = shape_geometry(first).bounds, shape_geometry(second).bounds
    assert a[1][0] < b[0][0]
    assert np.isclose(b[0][0] - a[1][0], 10.0, atol=1e-6)


def test_pegs_and_matching_snug_holes():
    first, second = split(block(), "z", 10.0, pegs=True, peg_diameter=4.0, clearances=CLEAR)
    t1, t2 = shape_geometry(first), shape_geometry(second)
    assert t1.is_watertight and t2.is_watertight

    pegs = [c for c in ungroup(first) if c.name == "Peg"]
    holes = [c for c in ungroup(second) if c.name == "Peg hole"]
    assert len(pegs) == len(holes) == 2
    assert all(h.is_hole and h.fit == "snug" for h in holes)
    assert all(not p.is_hole for p in pegs)

    # Pegs stick out 4 mm; each 4 mm peg adds pi*2^2*4.
    assert np.isclose(t1.volume, 12000.0 + 2 * np.pi * 4.0 * 4.0, rtol=2e-3)
    # Holes are 4.4 mm across (snug, 0.2 per side), 4.5 + 0.2 deep inside the part.
    assert np.isclose(t2.volume, 12000.0 - 2 * np.pi * 2.2**2 * 4.7, rtol=2e-3)
    # The peg half rests the other way up: pegs point up, so it is 14 tall.
    assert np.isclose(t1.bounds[1][2], 14.0, atol=1e-6)


def test_pegs_and_holes_line_up_when_the_halves_are_put_back():
    first, second = split(block(), "x", 0.0, pegs=True, clearances=CLEAR)
    # The halves are laid out apart, so compare the children's stored
    # (pre-layout) positions: their Y/Z on the cut plane match pairwise.
    raw_pegs = sorted(tuple(np.round(d["transform"][i][3], 6) for i in (1, 2))
                      for d in first.params["children"] if d["name"] == "Peg")
    raw_holes = sorted(tuple(np.round(d["transform"][i][3], 6) for i in (1, 2))
                       for d in second.params["children"] if d["name"] == "Peg hole")
    assert raw_pegs == raw_holes and len(raw_pegs) == 2


def test_a_cut_outside_the_part_is_refused():
    with pytest.raises(BuildError, match="misses"):
        split(block(), "z", 25.0)


def test_pegs_too_big_for_the_cut_are_refused():
    with pytest.raises(BuildError, match="room for pegs"):
        split(block(w=8.0, d=8.0), "z", 10.0, pegs=True, peg_diameter=6.0)


def test_a_thin_half_without_room_for_peg_holes_is_refused():
    # Cutting 1 mm from the top leaves no depth for 4 mm peg holes.
    with pytest.raises(BuildError, match="room for pegs"):
        split(block(), "z", 19.0, pegs=True, peg_diameter=4.0, clearances=CLEAR)


def test_holes_cannot_be_split():
    part = block()
    part.is_hole = True
    with pytest.raises(BuildError):
        split(part, "z", 10.0)


def test_a_sphere_splits_into_two_watertight_domes():
    ball = new_primitive("sphere")
    first, second = split(ball, "z", 10.0)
    for part in (first, second):
        tm = shape_geometry(part)
        assert tm.is_watertight
        assert np.isclose(tm.bounds[1][2] - tm.bounds[0][2], 10.0, atol=0.05)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_split_in_the_window_is_one_undo_step(window):
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.split_selected("z", 10.0, pegs=True) is True
    scene = window.document.scene
    assert len(scene.shapes) == 2 and all(s.kind == "group" for s in scene.shapes)
    assert set(scene.selection) == {s.id for s in scene.shapes}
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert len(window.document.scene.shapes) == 1


def test_a_failed_split_leaves_no_undo_step(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    window.add_primitive("cube")
    depth = len(window.document._undo)
    assert window.split_selected("z", 50.0) is False
    assert len(window.document._undo) == depth
    assert len(window.document.scene.shapes) == 1
    assert len(warnings) == 1


def test_split_dialog_values_reach_the_tool(window, monkeypatch):
    from mesh import panels

    monkeypatch.setattr(panels, "run_form", lambda *a, **k: {
        "axis": "x", "distance": 5.0, "pegs": False, "peg_diameter": 4.0,
    })
    window.add_primitive("cube")  # x from -10 to 10
    window.do_split()
    widths = sorted(round(float(shape_geometry(s).volume)) for s in window.document.scene.shapes)
    assert widths == [2000, 6000]
