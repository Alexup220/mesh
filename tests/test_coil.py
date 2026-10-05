"""Coil (Expert mode's Create menu): a spring, a wire wound round an upright line."""

import math

import numpy as np
import pytest
import trimesh

from mesh import coils, construct, create, expert_actions, modify, parameters
from mesh.builders import BuildError
from mesh.expert import TOOLS
from mesh.io_formats import load_project, save_project
from mesh.panels import FIELD_LABELS, FormDialog
from mesh.scene import Scene
from mesh.settings import Settings
from mesh.shapes import PRIMITIVES, shape_geometry
from mesh.solids import to_manifold
from test_plain_language import assert_plain

SPRING = {"diameter": 20.0, "pitch": 5.0, "turns": 5.0, "wire": 2.0}


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow(Settings(expert_mode=True)))


@pytest.fixture
def warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))
    return seen


def section_area(wire_shape: str, half: float) -> float:
    if wire_shape == "square":
        return (2 * half) ** 2
    n = coils.WIRE_SEGMENTS
    return n / 2 * half ** 2 * math.sin(2 * math.pi / n)


def wire_middle_angle(tm, z):
    """Which way round the wire is, at height z (degrees)."""
    points = trimesh.intersections.mesh_plane(tm, (0, 0, 1), (0, 0, z)).reshape(-1, 3)
    middle = points.mean(axis=0)
    return math.degrees(math.atan2(middle[1], middle[0]))


# --- The coil ----------------------------------------------------------------------------


@pytest.mark.parametrize("wire_shape", ["round", "square"])
def test_a_coil_is_a_closed_spring_of_its_sizes(wire_shape):
    tm = coils.coil_mesh({**SPRING, "wire_shape": wire_shape})
    assert tm.is_watertight and tm.is_winding_consistent and tm.volume > 0
    # 20 mm across the outside, standing on the workplane, as tall as the
    # turns rise plus the wire.
    assert tm.bounds[:, 2].tolist() == pytest.approx([0, 5 * 5 + 2], abs=1e-6)
    assert np.ptp(tm.bounds[:, 0]) == pytest.approx(20, abs=0.01)
    # The wire's outline carried round the middle line: its area times the
    # way its middle goes round (the rise adds nothing).
    expected = section_area(wire_shape, 1.0) * 2 * math.pi * 9.0 * 5
    assert tm.volume == pytest.approx(expected, rel=0.005)
    # Seen from above it is a ring 2 mm wide: nothing within 8 mm of the middle.
    radius = np.hypot(tm.vertices[:, 0], tm.vertices[:, 1])
    assert radius.min() == pytest.approx(8.0, abs=0.05) and radius.max() == pytest.approx(10.0, abs=1e-6)


def test_a_right_hand_coil_climbs_anticlockwise_seen_from_above():
    right = coils.coil_mesh({**SPRING, "wire": 1.0})
    # A quarter of a pitch higher, the wire is a quarter turn further round.
    turned = (wire_middle_angle(right, 10.0 + 5.0 / 4) - wire_middle_angle(right, 10.0)) % 360
    assert turned == pytest.approx(90, abs=3)
    left = coils.coil_mesh({**SPRING, "wire": 1.0, "winding": "left"})
    assert (wire_middle_angle(left, 10.0 + 5.0 / 4) - wire_middle_angle(left, 10.0)) % 360 == pytest.approx(270, abs=3)
    assert left.volume == pytest.approx(right.volume)


def test_part_turns_and_the_ends_are_cut_across_the_wire():
    tm = coils.coil_mesh({**SPRING, "turns": 2.25})
    assert tm.is_watertight
    assert tm.bounds[1, 2] == pytest.approx(2.25 * 5 + 2, abs=1e-6)
    # The first end lies in the upright plane through the middle line,
    # along +X: its points all have y = 0.
    start = tm.vertices[np.abs(tm.vertices[:, 2] - 1.0) < 1.01]
    first = start[np.abs(np.arctan2(start[:, 1], start[:, 0])) < 0.01]
    assert len(first) >= coils.WIRE_SEGMENTS and np.abs(first[:, 1]).max() < 1e-6


def test_a_fitted_coil_hole_grows_all_round():
    plain = coils.coil_mesh(SPRING)
    grown = coils.coil_mesh(SPRING, 0.2)
    assert grown.is_watertight
    assert np.ptp(grown.bounds[:, 0]) == pytest.approx(20.4, abs=0.01)
    assert grown.bounds[0, 2] < -0.19 and grown.bounds[1, 2] > 27.19
    assert (to_manifold(plain) - to_manifold(grown)).volume() == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("change, clearance, words", [
    ({"pitch": 2.0}, 0.0, "more than the wire"),
    ({"pitch": 2.3}, 0.2, "smaller fit"),
    ({"wire": 9.98, "pitch": 12.0}, 0.0, "too thick"),
    ({"wire": 0.05}, 0.0, "at least 0.1 mm"),
    ({"turns": 0.0}, 0.0, "turns"),
    ({"turns": 500.0}, 0.0, "turns"),
    ({"diameter": float("nan")}, 0.0, "ordinary numbers"),
    ({"wire_shape": "flat"}, 0.0, "round or square"),
    ({"winding": "up"}, 0.0, "which way"),
])
def test_sizes_that_cannot_make_a_coil_are_refused(change, clearance, words):
    with pytest.raises(coils.CoilError) as err:
        coils.coil_mesh({**SPRING, **change}, clearance)
    assert words in str(err.value)
    assert_plain(str(err.value))


# --- As a part ---------------------------------------------------------------------------


def test_a_new_coil_is_a_part_with_editable_sizes():
    made = create.make_coil(16.0, 4.0, 3.5, 1.5, "square", "left", hole=True)
    assert made.params == {"primitive": "coil", "diameter": 16.0, "pitch": 4.0, "turns": 3.5, "wire": 1.5,
                           "wire_shape": "square", "winding": "left"}
    assert made.is_hole and not PRIMITIVES["coil"]["shelf"]
    assert set(parameters.linkable(made)) >= {"diameter", "pitch", "turns", "wire"}
    with pytest.raises(BuildError) as err:
        create.make_coil(16.0, 1.0, 3.5, 1.5)
    assert "more than the wire" in str(err.value)


def test_details_edits_and_fits_on_a_coil_are_checked():
    coil = create.make_coil(20.0, 5.0, 5.0, 2.0)
    assert create.edit_refusal(coil, "turns", 8.0, None) is None
    assert "more than the wire" in create.edit_refusal(coil, "wire", 6.0, None)
    assert "which way" in create.edit_refusal(coil, "winding", "up", None)
    coil.is_hole, coil.fit = True, "loose"
    assert create.fit_refusal([coil], {"press": 0.1, "snug": 0.2, "loose": 0.4}) is None
    assert "smaller fit" in create.fit_refusal([coil], {"press": 0.1, "snug": 0.2, "loose": 1.6})


def test_a_coil_scales_only_alike_in_every_direction():
    coil = create.make_coil(20.0, 5.0, 5.0, 2.0)
    [bigger] = modify.scaled([coil], (2, 2, 2))
    assert [bigger.params[k] for k in ("diameter", "pitch", "turns", "wire")] == [40, 10, 5, 4]
    with pytest.raises(BuildError) as err:
        modify.scaled([coil], (1, 1, 2))
    assert "is round" in str(err.value)


def test_a_coil_has_an_upright_middle_line():
    coil = create.make_coil(20.0, 5.0, 5.0, 2.0)
    coil.transform[:3, 3] = (4, 5, 6)
    point, direction = construct.axis_of(coil)
    assert point.tolist() == [4, 5, 6] and direction.tolist() == pytest.approx([0, 0, 1])


def test_a_coil_round_trips_through_a_project_file(tmp_path):
    coil = create.make_coil(16.0, 4.0, 3.5, 1.5, "square", "left", hole=True)
    file = tmp_path / "coil.mesh"
    save_project(Scene(shapes=[coil]), file)
    loaded = load_project(file).shapes[0]
    assert loaded.params == coil.params and loaded.is_hole
    assert shape_geometry(loaded).volume == pytest.approx(shape_geometry(coil).volume)


# --- In the window -----------------------------------------------------------------------


def test_making_a_coil_is_one_undo_step(window, monkeypatch):
    monkeypatch.setattr(expert_actions, "ask_coil", lambda parent: {
        "diameter": 30.0, "pitch": 6.0, "turns": 4.0, "wire": 3.0, "wire_shape": "round",
        "winding": "right", "result": "part"})
    steps = len(window.document._undo)
    window.do_coil()
    [coil] = window.document.scene.shapes
    assert coil.params["primitive"] == "coil" and coil.params["diameter"] == 30.0 and not coil.is_hole
    assert window.document.scene.selection == [coil.id]
    assert len(window.document._undo) == steps + 1
    assert window.inspector.visible_param_fields() == set(coils.DEFAULTS)
    window.do_undo()
    assert window.document.scene.shapes == []


def test_a_refused_coil_leaves_no_undo_step(window, warnings):
    steps = len(window.document._undo)
    assert not window.add_coil(20.0, 1.0, 5.0, 2.0)
    assert warnings and "more than the wire" in warnings[0]
    assert window.document.scene.shapes == [] and len(window.document._undo) == steps


def test_a_details_edit_that_cannot_make_a_coil_is_refused(window, warnings):
    window.add_coil()
    coil = window.document.scene.shapes[0]
    window._on_edited(coil.id, "wire", 7.0)
    assert warnings and "more than the wire" in warnings[0] and coil.params["wire"] == 2.0
    window._on_edited(coil.id, "turns", 7.0)
    window._finish_edit()
    assert coil.params["turns"] == 7.0


def test_coil_text_is_plain_language(qapp, close_qt_widget):
    dialog = close_qt_widget(FormDialog(None, "Coil", expert_actions.coil_fields(), note=expert_actions.COIL_NOTE))
    for text in dialog.labels():
        assert_plain(text)
    for text in (*(FIELD_LABELS[f] for f in coils.DEFAULTS),
                 *(label for _, label in coils.WIRE_SHAPES + coils.WINDINGS),
                 PRIMITIVES["coil"]["label"], construct.NOT_ROUND,
                 *(t.tip for t in TOOLS if t.key == "coil")):
        assert_plain(text)
