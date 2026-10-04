"""Mirror (Expert mode): mirror-image copies across a plane, a sketch's plane or a clicked face."""

import numpy as np
import pytest

from mesh import create, pattern_actions, patterns, sketch
from mesh.builders import BuildError
from mesh.io_formats import load_project, save_project
from mesh.scene import Scene, new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain

SQUARE = [{"type": "rectangle", "corner": [0, 0], "width": 10, "height": 10}]


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


def middle(shape):
    return tuple(np.round(shape_geometry(shape).bounds.mean(axis=0), 6))


def corners(shape):
    return sorted(map(tuple, np.round(shape_geometry(shape).vertices, 6)))


def face_towards(shape, direction):
    tm = shape_geometry(shape)
    return int(np.argmax(tm.face_normals @ np.asarray(direction, dtype=np.float64)))


def lopsided():
    """A wedge moved and turned, so only a true reflection matches it."""
    wedge = new_primitive("wedge")
    turn = np.radians(30.0)
    wedge.transform[:2, :2] = [[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]]
    wedge.transform[:3, 3] = (20.0, 5.0, 0.0)
    return wedge


# --- The reflection ---------------------------------------------------------------------


def test_a_mirrored_copy_is_the_part_reflected_across_the_plane():
    wedge = lopsided()
    [copy] = patterns.mirrored([wedge], (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    flipped = sorted((-x, y, z) for x, y, z in corners(wedge))
    assert corners(copy) == [pytest.approx(c, abs=1e-6) for c in flipped]
    tm = shape_geometry(copy)
    assert tm.is_volume and tm.volume == pytest.approx(shape_geometry(wedge).volume)
    assert np.linalg.det(copy.transform[:3, :3]) == pytest.approx(-1.0)


def test_a_plane_away_from_zero_moves_the_copy_across_it():
    [copy] = patterns.mirrored([new_primitive("cube")], (10.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert shape_geometry(copy).bounds[:, 0] == pytest.approx([10.0, 30.0])
    [copy] = patterns.mirrored([new_primitive("cube")], (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert shape_geometry(copy).bounds[:, 2] == pytest.approx([-20.0, 0.0])


def test_a_sloping_plane_reflects_too():
    [copy] = patterns.mirrored([new_primitive("sphere")], (30.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    # The ball's middle (0, 0, 10) lands across the plane x + y = 30.
    assert middle(copy) == pytest.approx((30.0, 30.0, 10.0), abs=1e-6)


def test_copies_keep_their_kind_and_are_named_as_mirrored():
    box, hole = new_primitive("cube"), new_primitive("cylinder")
    hole.is_hole, hole.fit = True, "snug"
    copies = patterns.mirrored([box, hole], (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert [c.name for c in copies] == [f"{box.name} (mirrored)", f"{hole.name} (mirrored)"]
    assert [c.is_hole for c in copies] == [False, True] and copies[1].fit == "snug"
    assert {c.id for c in copies}.isdisjoint({box.id, hole.id})
    assert copies[0].params == box.params


def test_sketches_are_not_mirrored():
    with pytest.raises(BuildError) as err:
        patterns.mirrored([create.new_sketch(SQUARE, np.eye(4))], (0, 0, 0), (1, 0, 0))
    assert "flat drawing" in str(err.value)
    assert_plain(str(err.value))


def test_the_planes_mirror_can_use():
    guide = create.new_sketch(SQUARE, sketch.plane_frame((1.0, 0.0, 0.0), (15.0, 0.0, 0.0)))
    origin, normal = patterns.plane_of_sketch(guide)
    assert origin == pytest.approx([15.0, 0.0, 0.0]) and normal == pytest.approx([1.0, 0.0, 0.0])
    box = new_primitive("cube")
    centre, normal = patterns.plane_of_face(box, face_towards(box, (0, 0, 1)))
    assert centre == pytest.approx([0.0, 0.0, 20.0]) and normal == pytest.approx([0.0, 0.0, 1.0])
    origin, normal = patterns.middle_plane("y")
    assert origin == pytest.approx([0.0, 0.0, 0.0]) and normal == pytest.approx([0.0, 1.0, 0.0])


# --- In the window ----------------------------------------------------------------------


def add_box(window, x=0.0):
    window.add_primitive("cube")
    box = window.document.scene.shapes[-1]
    box.transform[0, 3] = x
    window.sync()
    return box


def test_mirroring_is_one_undo_step_and_selects_the_parts_and_copies(window):
    box = add_box(window, 20.0)
    steps = len(window.document._undo)
    assert window.mirror_copy_selected("x")
    scene = window.document.scene
    assert len(scene.shapes) == 2 and len(window.document._undo) == steps + 1
    assert middle(scene.shapes[1]) == (-20, 0, 10) and scene.shapes[1].name.endswith("(mirrored)")
    assert scene.selection == [box.id, scene.shapes[1].id]
    window.do_undo()
    assert [s.id for s in window.document.scene.shapes] == [box.id]


def test_with_a_sketch_selected_mirror_uses_its_plane_without_asking(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: pytest.fail("no form with a sketch"))
    box = add_box(window)
    window.add_sketch(SQUARE, sketch.plane_frame((1.0, 0.0, 0.0), (30.0, 0.0, 0.0)))
    guide = window.document.scene.shapes[1]
    window.document.scene.select([box.id, guide.id])
    window.do_mirror_copy()
    shapes = window.document.scene.shapes
    assert len(shapes) == 3 and middle(shapes[2]) == (60, 0, 10)
    assert guide.id not in window.document.scene.selection


def test_the_form_mirrors_across_a_middle_plane(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: {"plane": "y"})
    box = add_box(window)
    box.transform[1, 3] = 15.0
    window.do_mirror_copy()
    assert middle(window.document.scene.shapes[1]) == (0, -15, 10)


def test_mirror_across_a_clicked_face(window, monkeypatch, qapp):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: {"plane": "face"})
    wall = add_box(window, 40.0)
    box = add_box(window)
    window.document.scene.select([box.id])
    window.do_mirror_copy()
    assert window.tool == "mirror_face"
    steps = len(window.document._undo)
    window._on_surface_picked(wall.id, face_towards(wall, (-1, 0, 0)), (30, 0, 10))
    assert window.tool is None and len(window.document._undo) == steps
    qapp.processEvents()  # mirrored once the click is over
    shapes = window.document.scene.shapes
    assert len(shapes) == 3 and len(window.document._undo) == steps + 1
    assert middle(shapes[2]) == (60, 0, 10)  # across the wall's left face, at 30
    window.do_undo()
    assert len(window.document.scene.shapes) == 2


def test_a_click_off_a_part_or_on_a_sketch_keeps_mirror_waiting(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: {"plane": "face"})
    box = add_box(window)
    window.add_sketch(SQUARE, np.eye(4))
    window.document.scene.select([box.id])
    window.do_mirror_copy()
    window._on_surface_picked("", -1, (0, 0, 0))
    window._on_surface_picked(window.document.scene.shapes[1].id, 0, (0, 0, 0))
    window._on_surface_picked(box.id, -1, (0, 0, 0))
    assert window.tool == "mirror_face"
    assert window.statusBar().currentMessage() == window.TOOL_PROMPTS["mirror_face"]
    assert len(window.document.scene.shapes) == 2


def test_esc_and_turning_expert_mode_off_stop_mirror(window, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: {"plane": "face"})
    add_box(window)
    window.do_mirror_copy()
    window.stop_tool()
    assert window.tool is None
    window.do_mirror_copy()
    assert window.tool == "mirror_face"
    window.set_expert_mode(False)
    assert window.tool is None


def test_mirror_needs_parts_and_at_most_one_sketch(window, warnings, monkeypatch):
    monkeypatch.setattr(pattern_actions, "ask_mirror", lambda parent: pytest.fail("no form"))
    window.do_mirror_copy()
    assert window.statusBar().currentMessage() == window.MIRROR_HINT
    add_box(window)
    window.add_sketch(SQUARE, np.eye(4))
    window.do_mirror_copy()  # only the sketch is selected
    assert window.statusBar().currentMessage() == window.MIRROR_HINT
    window.add_sketch(SQUARE, np.eye(4))
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_mirror_copy()
    assert window.statusBar().currentMessage() == window.MIRROR_HINT
    assert len(window.document.scene.shapes) == 3 and not warnings


def test_a_face_that_cannot_be_used_changes_nothing(window, warnings):
    box = add_box(window)
    steps = len(window.document._undo)
    assert not window.mirror_across_face(box.id, -1, [box.id])
    assert warnings and len(window.document._undo) == steps and len(window.document.scene.shapes) == 1


def test_parts_removed_before_the_click_mirror_nothing(window):
    box = add_box(window)
    wall = add_box(window, 40.0)
    assert not window.mirror_across_face(wall.id, face_towards(wall, (-1, 0, 0)), ["gone"])
    assert window.statusBar().currentMessage() == window.MIRROR_HINT
    assert [s.id for s in window.document.scene.shapes] == [box.id, wall.id]


def test_mirrored_copies_round_trip_through_a_project_file(tmp_path):
    wedge = lopsided()
    shapes = [wedge] + patterns.mirrored([wedge], (5.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    file = tmp_path / "parts.mesh"
    save_project(Scene(shapes=shapes), file)
    loaded = load_project(file).shapes
    assert [corners(s) for s in loaded] == [corners(s) for s in shapes]
    assert loaded[1].name == shapes[1].name
    assert shape_geometry(loaded[1]).volume == pytest.approx(shape_geometry(wedge).volume)


def test_mirror_form_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Mirror", pattern_actions.mirror_fields(),
                                        note=pattern_actions.MIRROR_NOTE))
    for text in dialog.labels():
        assert_plain(text)
    assert_plain(pattern_actions.PatternActions.MIRROR_HINT)
    assert_plain(pattern_actions.PatternActions.PATTERN_TOOL_PROMPTS["mirror_face"])
