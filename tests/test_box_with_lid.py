"""Box with lid: two watertight parts whose lip and recess fit by the clearance."""

import numpy as np
import pytest

from mesh.blobs import decode_mesh
from mesh.builders import BuildError, box_with_lid
from mesh.scene import DEFAULT_FIT_CLEARANCES
from mesh.shapes import shape_geometry
from mesh.solids import to_manifold

CLEAR = dict(DEFAULT_FIT_CLEARANCES)


def closed(part):
    """The part where it sits when the box is closed: its stored result,
    before the layout transform."""
    return decode_mesh(part.params["blob"])


@pytest.mark.parametrize("fit, c", [("exact", 0.0), ("snug", 0.2), ("loose", 0.4)])
def test_volumes_match_the_design(fit, c):
    w, d, h, t, hl = 60.0, 40.0, 30.0, 2.0, 6.0
    body, lid = box_with_lid(w, d, h, t, hl, fit, CLEAR)
    bh, lip = h - hl, 3.0
    tb, tl = shape_geometry(body), shape_geometry(lid)
    assert tb.is_watertight and tl.is_watertight

    body_v = w * d * bh - (w - 2 * t) * (d - 2 * t) * (bh - t) \
        - ((w - t) * (d - t) - (w - 2 * t) * (d - 2 * t)) * lip
    assert np.isclose(tb.volume, body_v, rtol=1e-9)

    ring = (w - t - 2 * c) * (d - t - 2 * c) - (w - 2 * t) * (d - 2 * t)
    lid_v = w * d * hl - (w - 2 * t) * (d - 2 * t) * (hl - t) + ring * (lip - c)
    assert np.isclose(tl.volume, lid_v, rtol=1e-6)  # stored as float32 STL


def test_closed_lid_fits_without_touching_and_with_the_clearance():
    body, lid = box_with_lid(50.0, 50.0, 20.0, 2.4, 5.0, "snug", CLEAR)
    tb, tl = closed(body), closed(lid)
    tl.apply_translation((0.0, 0.0, 15.0))  # lid underside on the box rim
    overlap = (to_manifold(tb) ^ to_manifold(tl)).volume()
    assert overlap < 1e-6
    # Closed, the whole thing is the outside height asked for.
    assert np.isclose(max(tb.bounds[1][2], tl.bounds[1][2]), 20.0)
    # The lip is 0.2 mm in from the recess on each side.
    lip_width = tl.bounds[1][0] - tl.bounds[0][0]
    section = tl.section(plane_origin=(0, 0, 13.0), plane_normal=(0, 0, 1))
    lip_outer = section.bounds[1][0] - section.bounds[0][0]
    assert np.isclose(lip_width, 50.0)
    assert np.isclose(lip_outer, 50.0 - 2.4 - 0.4, atol=1e-6)


def test_parts_lie_side_by_side_lid_upside_down():
    body, lid = box_with_lid(60.0, 40.0, 30.0, 2.0, 6.0, "snug", CLEAR)
    tb, tl = shape_geometry(body), shape_geometry(lid)
    assert np.isclose(tb.bounds[0][2], 0.0) and np.isclose(tl.bounds[0][2], 0.0)
    assert tb.bounds[1][0] < tl.bounds[0][0]
    # Upside down: the flat top of the lid is on the bed (a 60 x 40 face).
    down = tl.face_normals[:, 2] < -0.999
    assert np.isclose(tl.area_faces[down].sum(), 2400.0)


@pytest.mark.parametrize("args", [
    (60, 40, 30, 0.0, 6),     # no wall
    (10, 10, 30, 5.0, 6),     # walls meet
    (60, 40, 30, 2.0, 1.0),   # lid thinner than the wall
    (60, 40, 8, 2.0, 6.0),    # lid leaves no box
    (60, 40, 30, 0.8, 6.0),   # too thin for a snug lip
])
def test_impossible_boxes_are_refused(args):
    with pytest.raises(BuildError):
        box_with_lid(*args, "snug", CLEAR)


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_box_with_lid_in_the_window_is_one_undo_step(window):
    depth = len(window.document._undo)
    assert window.make_box_with_lid(60.0, 40.0, 30.0, 2.0, 6.0, "loose") is True
    scene = window.document.scene
    assert [s.name for s in scene.shapes] == ["Box", "Lid"]
    assert len(scene.selection) == 2
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert window.document.scene.shapes == []


def test_a_refused_box_leaves_no_undo_step(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    depth = len(window.document._undo)
    assert window.make_box_with_lid(10.0, 10.0, 30.0, 5.0, 6.0) is False
    assert len(window.document._undo) == depth and window.document.scene.shapes == []
    assert len(seen) == 1


def test_dialog_values_reach_the_generator(window, monkeypatch):
    from mesh import panels

    def accept_defaults(parent, title, fields, note=None):
        return {key: default for key, _label, default, _o in fields}

    monkeypatch.setattr(panels, "run_form", accept_defaults)
    window.do_box_with_lid()
    assert len(window.document.scene.shapes) == 2


# --- review fixes -----------------------------------------------------------


def test_a_box_too_short_for_its_lid_fit_is_refused():
    clearances = {**DEFAULT_FIT_CLEARANCES, "loose": 1.0}
    with pytest.raises(BuildError, match="too short"):
        box_with_lid(60.0, 40.0, 10.5, 3.0, 6.0, "loose", clearances)


def test_the_largest_fit_clearance_never_crashes():
    clearances = {**DEFAULT_FIT_CLEARANCES, "loose": 2.0}
    try:
        body, lid = box_with_lid(60.0, 40.0, 14.0, 5.0, 6.0, "loose", clearances)
    except BuildError:
        return
    assert shape_geometry(body).is_volume and shape_geometry(lid).is_volume


def test_the_wall_the_refusal_suggests_is_accepted():
    with pytest.raises(BuildError) as raised:
        box_with_lid(60.0, 40.0, 30.0, 1.0, 6.0, "snug", DEFAULT_FIT_CLEARANCES)
    suggested = float(str(raised.value).split("at least ")[1].split(" mm")[0])
    body, lid = box_with_lid(60.0, 40.0, 30.0, suggested, 6.0, "snug", DEFAULT_FIT_CLEARANCES)
    assert shape_geometry(lid).is_volume
