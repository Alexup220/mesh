"""Holes that swallow a whole part, and cuts that leave nothing behind.

The combine then returns no solid at all. Everything that measures the
result (the status bar check, Save as, Group) must say so in plain words
rather than crash.
"""

import re

import pytest

from mesh import ops
from mesh.io_formats import ProjectError, export_scene
from mesh.printcheck import check
from mesh.scene import Scene, new_primitive


def assert_plain(text: str) -> None:
    # The same forbidden words as tests/test_plain_language.py.
    for word in ("boolean", "csg", "manifold", "mesh", "vertex", "vertices", "normal", "offset"):
        assert not re.search(rf"\b{word}", text.lower()), f"jargon {word!r} in {text!r}"


def _swallowed_scene() -> Scene:
    """A solid cylinder with an identical hole cylinder on top of it."""
    scene = Scene()
    solid = new_primitive("cylinder")
    hole = new_primitive("cylinder")
    hole.is_hole = True
    scene.add(solid)
    scene.add(hole)
    return scene


def _apart_cubes():
    first = new_primitive("cube")
    second = new_primitive("cube")
    second.transform[:3, 3] = (100.0, 0.0, 0.0)
    return [first, second]


def test_evaluate_refuses_when_the_holes_cut_away_everything():
    with pytest.raises(ops.NothingLeftError):
        ops.evaluate(_swallowed_scene().shapes)


def test_nothing_left_is_a_kind_of_nothing_to_combine():
    # Existing callers that catch NothingToCombineError keep working.
    assert issubclass(ops.NothingLeftError, ops.NothingToCombineError)


def test_check_reports_an_empty_model_instead_of_crashing():
    report = check(_swallowed_scene())
    assert report.empty is True
    assert report.volume_mm3 == 0.0
    assert "cut away" in report.message
    assert_plain(report.message)


def test_export_refuses_with_a_plain_message(tmp_path):
    path = tmp_path / "out.stl"
    with pytest.raises(ProjectError) as raised:
        export_scene(_swallowed_scene(), path)
    assert "cut away" in str(raised.value)
    assert "gaps" not in str(raised.value)
    assert_plain(str(raised.value))
    assert not path.exists()


def test_group_refuses_rather_than_storing_nothing():
    with pytest.raises(ops.NothingLeftError) as raised:
        ops.make_group(_swallowed_scene().shapes)
    assert_plain(str(raised.value))


def test_keep_overlap_of_shapes_that_do_not_touch_refuses():
    with pytest.raises(ops.NothingLeftError) as raised:
        ops.make_boolean_group(_apart_cubes(), "intersection")
    assert "overlap" in str(raised.value)
    assert_plain(str(raised.value))


def test_cut_out_that_removes_everything_refuses():
    first, second = new_primitive("cube"), new_primitive("cube")
    with pytest.raises(ops.NothingLeftError) as raised:
        ops.make_boolean_group([first, second], "difference")
    assert_plain(str(raised.value))


def test_join_of_shapes_that_do_not_touch_still_works():
    group = ops.make_boolean_group(_apart_cubes(), "union")
    assert group.kind == "group"


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


@pytest.fixture
def warnings(monkeypatch):
    shown = []
    from mesh.app import MeshWindow

    monkeypatch.setattr(MeshWindow, "_warn", lambda self, title, text: shown.append((title, text)))
    return shown


def _load(window, scene: Scene) -> None:
    for shape in scene.shapes:
        window.document.scene.add(shape)
    window.sync()


def test_window_shows_a_plain_status_when_the_holes_cut_away_everything(window):
    _load(window, _swallowed_scene())
    assert "cut away" in window.statusBar().currentMessage()


def test_group_in_the_window_warns_and_adds_no_undo_step(window, warnings):
    _load(window, _swallowed_scene())
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    before = window.document.can_undo()
    window.do_group()
    assert len(window.document.scene.shapes) == 2
    assert all(s.kind == "primitive" for s in window.document.scene.shapes)
    assert window.document.can_undo() == before
    assert warnings and "cut away" in warnings[0][1]


def test_keep_overlap_in_the_window_warns_and_adds_no_undo_step(window, warnings):
    for shape in _apart_cubes():
        window.document.scene.add(shape)
    window.sync()
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    before = window.document.can_undo()
    window.do_boolean("intersection")
    assert len(window.document.scene.shapes) == 2
    assert window.document.can_undo() == before
    assert warnings and "overlap" in warnings[0][1]


# --- parts with gaps ----------------------------------------------------------


def _open_part():
    import numpy as np
    import trimesh

    from mesh.blobs import encode_mesh
    from mesh.scene import Shape

    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box.update_faces(np.arange(len(box.faces) - 1))  # one triangle missing
    return Shape(id="open", name="Open box", kind="imported",
                 params={"blob": encode_mesh(box)}, transform=np.eye(4))


def _scene_with_open_part() -> Scene:
    scene = Scene()
    scene.add(_open_part())
    scene.add(new_primitive("cube"))
    return scene


def test_a_part_with_gaps_next_to_another_reports_gaps_instead_of_crashing():
    report = check(_scene_with_open_part())
    assert report.empty is False and report.watertight is False
    assert "gaps" in report.message
    assert_plain(report.message)


def test_saving_a_model_with_an_open_part_refuses_plainly(tmp_path):
    with pytest.raises(ProjectError, match="gaps"):
        export_scene(_scene_with_open_part(), tmp_path / "out.stl")


def test_grouping_an_open_part_refuses_with_no_undo_step(window, warnings):
    _load(window, _scene_with_open_part())
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    before = window.document.can_undo()
    window.do_group()
    assert len(window.document.scene.shapes) == 2
    assert window.document.can_undo() == before
    assert warnings and "gaps" in warnings[0][1]
    assert_plain(warnings[0][1])
