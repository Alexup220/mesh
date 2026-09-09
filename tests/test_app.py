import numpy as np
import pytest
import trimesh


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_window_constructs_with_an_empty_document(window):
    assert window.document.scene.shapes == []


def test_add_primitive_adds_and_selects_it(window):
    window.add_primitive("cube")
    assert len(window.document.scene.shapes) == 1
    assert window.document.scene.selection == [window.document.scene.shapes[0].id]


def test_add_primitive_is_undoable(window):
    window.add_primitive("cube")
    window.do_undo()
    assert window.document.scene.shapes == []


def test_toggle_hole_flips_the_selection(window):
    window.add_primitive("cube")
    window.do_toggle_hole()
    assert window.document.scene.shapes[0].is_hole is True


def test_group_replaces_the_selection_with_one_shape(window):
    window.add_primitive("cube")
    window.add_primitive("sphere")
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_group()
    assert len(window.document.scene.shapes) == 1
    assert window.document.scene.shapes[0].kind == "group"


def test_ungroup_restores_the_children(window):
    window.add_primitive("cube")
    window.add_primitive("sphere")
    window.document.scene.select([s.id for s in window.document.scene.shapes])
    window.do_group()
    window.do_ungroup()
    assert len(window.document.scene.shapes) == 2


def test_delete_removes_the_selection(window):
    window.add_primitive("cube")
    window.do_delete()
    assert window.document.scene.shapes == []


def test_duplicate_adds_a_second_shape(window):
    window.add_primitive("cube")
    window.do_duplicate()
    assert len(window.document.scene.shapes) == 2


def test_status_message_updates_after_adding(window):
    window.add_primitive("cube")
    window.update_status()
    assert "mm" in window.statusBar().currentMessage()


def test_group_with_nothing_selected_is_a_safe_no_op(window):
    window.do_group()
    assert window.document.scene.shapes == []


def test_export_writes_a_file(window, tmp_path):
    window.add_primitive("cube")
    path = tmp_path / "part.stl"
    window.export_to(path)
    assert np.isclose(trimesh.load(path).volume, 8000.0, rtol=1e-3)


def test_project_roundtrip_through_the_window(window, tmp_path):
    window.add_primitive("cube")
    path = tmp_path / "part.mesh"
    window.save_to(path)
    window.do_delete()
    window.open_from(path)
    assert len(window.document.scene.shapes) == 1


def test_editing_a_rotation_field_changes_the_transform_not_the_params(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    before = np.asarray(shape.transform, dtype=np.float64).copy()

    window._on_edited(shape.id, "ry", 45.0)

    shape = window.document.scene.get(shape.id)
    after = np.asarray(shape.transform, dtype=np.float64)
    assert not np.allclose(before, after)
    assert "ry" not in shape.params


def test_a_burst_of_edits_produces_exactly_one_undo_entry(window):
    """Typing "125" into a field used to fire valueChanged three times,
    each taking its own snapshot -- so one Ctrl+Z only undid the last
    keystroke. A whole burst should coalesce into one snapshot/undo entry,
    settled by _finish_edit() once typing pauses."""
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    before_undo_depth = len(window.document._undo)

    window._on_edited(shape.id, "width", 1.0)
    window._on_edited(shape.id, "width", 12.0)
    window._on_edited(shape.id, "width", 125.0)
    window._finish_edit()

    assert len(window.document._undo) == before_undo_depth + 1
    assert shape.params["width"] == 125.0

    window.do_undo()
    assert window.document.scene.get(shape.id).params["width"] == 20.0


def test_edit_burst_defers_sync_until_settled(window):
    window.add_primitive("cube")
    shape = window.document.scene.shapes[0]
    seen = []
    original_sync = window.sync
    window.sync = lambda *a, **k: seen.append(True) or original_sync(*a, **k)

    window._on_edited(shape.id, "width", 1.0)
    window._on_edited(shape.id, "width", 12.0)
    assert seen == []  # sync deferred while the burst is still active

    window._finish_edit()
    assert seen == [True]


def test_viewport_refresh_does_not_rebuild_an_unchanged_actor(window):
    window.add_primitive("cube")
    window.sync()
    shape = window.document.scene.shapes[0]
    actor = window.viewport.actor_for(shape.id)
    mapper = actor.GetMapper()
    original_input = mapper.GetInput()

    window.viewport.refresh()

    assert mapper.GetInput() is original_input


def test_printcheck_is_not_recomputed_for_an_unchanged_scene(window):
    from mesh import printcheck

    window.add_primitive("cube")
    window.update_status()

    calls = []
    original = printcheck._check
    printcheck._check = lambda scene: calls.append(1) or original(scene)
    try:
        window.update_status()
        window.update_status()
        assert calls == []
    finally:
        printcheck._check = original
