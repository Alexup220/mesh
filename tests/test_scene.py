import numpy as np
import pytest

from mesh.scene import Document, Scene, Shape, new_primitive


def test_new_primitive_has_defaults_and_sits_at_origin():
    s = new_primitive("cube")
    assert s.kind == "primitive"
    assert s.params["primitive"] == "cube"
    assert s.params["width"] == 20.0
    assert s.is_hole is False
    assert np.allclose(s.transform, np.eye(4))
    assert s.id


def test_ids_are_unique():
    assert new_primitive("cube").id != new_primitive("cube").id


def test_add_remove_and_get():
    scene = Scene()
    s = new_primitive("sphere")
    scene.add(s)
    assert scene.get(s.id) is s
    scene.remove([s.id])
    assert scene.shapes == []
    with pytest.raises(KeyError):
        scene.get(s.id)


def test_removing_a_shape_clears_it_from_selection():
    scene = Scene()
    s = new_primitive("cube")
    scene.add(s)
    scene.select([s.id])
    scene.remove([s.id])
    assert scene.selection == []


def test_selected_returns_shapes_in_scene_order():
    scene = Scene()
    a, b, c = new_primitive("cube"), new_primitive("sphere"), new_primitive("cone")
    for s in (a, b, c):
        scene.add(s)
    scene.select([c.id, a.id])
    assert [s.id for s in scene.selected()] == [a.id, c.id]


def test_scene_roundtrips_through_dict():
    scene = Scene()
    scene.add(new_primitive("cylinder"))
    scene.build_volume = (100.0, 110.0, 120.0)
    restored = Scene.from_dict(scene.to_dict())
    assert restored.build_volume == (100.0, 110.0, 120.0)
    assert restored.shapes[0].params["primitive"] == "cylinder"
    assert isinstance(restored.shapes[0].transform, np.ndarray)
    assert restored.shapes[0].transform.shape == (4, 4)


def test_undo_restores_previous_state():
    doc = Document()
    doc.snapshot("add")
    doc.scene.add(new_primitive("cube"))
    assert len(doc.scene.shapes) == 1
    assert doc.undo() is True
    assert len(doc.scene.shapes) == 0
    assert doc.redo() is True
    assert len(doc.scene.shapes) == 1


def test_undo_on_empty_history_returns_false():
    assert Document().undo() is False


def test_new_snapshot_discards_the_redo_branch():
    doc = Document()
    doc.snapshot("a")
    doc.scene.add(new_primitive("cube"))
    doc.undo()
    doc.snapshot("b")
    doc.scene.add(new_primitive("sphere"))
    assert doc.can_redo() is False


def test_history_is_capped_at_fifty():
    doc = Document()
    for _ in range(80):
        doc.snapshot("x")
        doc.scene.add(new_primitive("cube"))
    assert len(doc._undo) <= 50
