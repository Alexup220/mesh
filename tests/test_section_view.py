"""Section view (Expert mode's Inspect menu)."""

import numpy as np
import pytest
import trimesh

from mesh import construct, inspect_actions, section
from mesh.expert import TOOLS
from mesh.io_formats import save_project
from mesh.scene import new_primitive
from mesh.settings import Settings
from mesh.shapes import shape_geometry
from test_plain_language import assert_plain


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow(Settings(expert_mode=True)))


def closed(*parts):
    whole = trimesh.util.concatenate(parts)
    whole.merge_vertices()
    return whole


# --- Cutting the drawing ----------------------------------------------------------------


def test_a_cut_keeps_the_side_away_from_the_way_the_plane_faces():
    tm = shape_geometry(new_primitive("cube"))
    kept, face_map, cap = section.cut_away(tm, (0, 0, 7), (0, 0, 1))
    assert kept.bounds[:, 2].tolist() == pytest.approx([0, 7])
    assert cap.bounds[:, 2].tolist() == pytest.approx([7, 7]) and cap.area == pytest.approx(400)
    assert closed(kept, cap).volume == pytest.approx(20 * 20 * 7)
    flipped, _, _ = section.cut_away(tm, (0, 0, 7), (0, 0, -1))
    assert flipped.bounds[:, 2].tolist() == pytest.approx([7, 20])


def test_every_kept_triangle_knows_the_part_face_it_came_from():
    tm = shape_geometry(new_primitive("cylinder"))
    kept, face_map, _ = section.cut_away(tm, (3, 0, 0), (1, 1, 0))
    assert len(face_map) == len(kept.faces) > 0
    assert np.abs((kept.face_normals * tm.face_normals[face_map]).sum(axis=1) - 1).max() < 1e-4


def test_a_round_cut_is_closed_by_a_round_cap():
    tm = shape_geometry(new_primitive("cylinder"))
    _, _, cap = section.cut_away(tm, (0, 0, 5), (0, 0, 1))
    assert cap.area == pytest.approx(np.pi * 10 ** 2, rel=0.01)


def test_a_plane_that_misses_the_part_keeps_all_or_nothing():
    tm = shape_geometry(new_primitive("cube"))
    kept, face_map, cap = section.cut_away(tm, (0, 0, 50), (0, 0, 1))
    assert kept.volume == pytest.approx(tm.volume) and len(cap.faces) == 0
    kept, face_map, cap = section.cut_away(tm, (0, 0, -1), (0, 0, 1))
    assert len(kept.faces) == 0 and len(face_map) == 0


def test_a_part_with_gaps_keeps_its_triangles_behind_the_plane():
    tm = shape_geometry(new_primitive("cube"))
    open_box = trimesh.Trimesh(vertices=tm.vertices, faces=tm.faces[:-2], process=False)
    kept, face_map, cap = section.cut_away(open_box, (0, 0, 7), (0, 0, 1))
    assert len(cap.faces) == 0 and len(kept.faces) == len(face_map) > 0
    assert (open_box.triangles_center[face_map][:, 2] <= 7).all()


def test_a_section_needs_a_direction():
    with pytest.raises(ValueError):
        section.where((0, 0, 0), (0, 0, 0))


# --- In the window ----------------------------------------------------------------------


def drawn_bounds(window, shape_id):
    return np.array(window.viewport.actor_for(shape_id).GetMapper().GetInput().GetBounds()).reshape(3, 2)


def add(window, kind):
    window.add_primitive(kind)
    return window.document.scene.shapes[-1]


def test_a_flat_section_through_the_middle_only_changes_the_view(window):
    box = add(window, "cube")
    steps, revision = len(window.document._undo), window.document.revision
    before = box.transform.copy()
    assert window.section_view("xy")
    origin, normal = window.viewport.section
    assert origin.tolist() == [0, 0, 10] and normal.tolist() == [0, 0, 1]
    assert drawn_bounds(window, box.id)[2].tolist() == pytest.approx([0, 10])
    assert window.viewport.cap_for(box.id) is not None
    assert window.statusBar().currentMessage() == window.SECTION_ON
    assert len(window.document._undo) == steps and window.document.revision == revision
    assert (box.transform == before).all() and shape_geometry(box).volume == pytest.approx(8000)


def test_choosing_section_view_again_shows_the_parts_whole(window, monkeypatch):
    asked = []
    monkeypatch.setattr(inspect_actions, "ask_section", lambda parent, selected: asked.append(
        selected) or {"plane": "yz", "distance": 4.0, "flip": True})
    box = add(window, "cube")
    window.do_section_view()
    assert asked == [None]
    origin, normal = window.viewport.section
    assert origin.tolist() == [4, 0, 10] and normal.tolist() == [-1, 0, 0]
    assert drawn_bounds(window, box.id)[0].tolist() == pytest.approx([4, 10])  # the other side
    window.do_section_view()
    assert asked == [None] and window.viewport.section is None
    assert window.viewport.cap_for(box.id) is None
    assert drawn_bounds(window, box.id)[0].tolist() == pytest.approx([-10, 10])
    assert window.statusBar().currentMessage() == window.SECTION_OFF


def test_a_section_along_a_selected_construction_plane(window, monkeypatch):
    seen = []
    monkeypatch.setattr(inspect_actions, "ask_section", lambda parent, selected: seen.append(
        selected) or {"plane": "selected", "distance": 0.0, "flip": False})
    box = add(window, "cube")
    window.document.scene.add(construct.new_plane((0, -3, 0), (0, -1, 0), name="Plane 1"))
    guide = window.document.scene.shapes[1]
    window.document.scene.select([guide.id])
    window.do_section_view()
    assert seen == ["Plane 1"]
    assert drawn_bounds(window, box.id)[1].tolist() == pytest.approx([-3, 10])
    # Guides are drawn whole.
    assert window.viewport.cap_for(guide.id) is None
    assert drawn_bounds(window, guide.id)[0].tolist() == pytest.approx([-30, 30])


def test_the_section_follows_parts_as_they_change(window):
    box = add(window, "cube")
    window.section_view("xy")
    box.transform[2, 3] = 5.0
    window.sync()
    assert drawn_bounds(window, box.id)[2].tolist() == pytest.approx([5, 10])
    hole = add(window, "cylinder")
    hole.is_hole = True
    window.sync()
    cap = window.viewport.cap_for(hole.id)
    assert cap is not None and cap.GetProperty().GetOpacity() < 1


def test_a_click_on_a_cut_part_still_finds_its_own_face(window):
    box = add(window, "cube")
    window.section_view("xz", 0.0)  # hides the front half
    tm = shape_geometry(box)
    drawn = window.viewport.actor_for(box.id).GetMapper().GetInput()
    for cell in range(drawn.GetNumberOfCells()):
        ids = drawn.GetCell(cell).GetPointIds()
        corners = np.array([drawn.GetPoint(ids.GetId(k)) for k in range(3)])
        face = window.viewport.face_of_cell(box.id, cell)
        assert abs((corners - tm.triangles[face][0]) @ tm.face_normals[face]).max() < 1e-4
    assert window.viewport.face_of_cell(box.id, 10_000) == -1
    assert window.viewport._shape_hit(window.viewport.cap_for(box.id)) == box.id


def test_a_section_needs_a_part(window):
    assert not window.section_view("xy")
    assert window.viewport.section is None
    assert window.statusBar().currentMessage() == window.SECTION_NEEDS_PARTS


def test_turning_expert_mode_off_shows_the_parts_whole(window):
    box = add(window, "cube")
    window.section_view("xy")
    window.set_expert_mode(False)
    assert window.viewport.section is None and window.viewport.cap_for(box.id) is None
    assert drawn_bounds(window, box.id)[2].tolist() == pytest.approx([0, 20])


def test_opening_a_project_shows_its_parts_whole(window, tmp_path):
    add(window, "cube")
    file = tmp_path / "part.mesh"
    save_project(window.document.scene, file)
    window.section_view("xy")
    window.open_from(file)
    assert window.viewport.section is None


def test_section_text_is_plain_language(qapp, close_qt_widget):
    from mesh.panels import FormDialog

    dialog = close_qt_widget(FormDialog(None, "Section View", inspect_actions.section_fields("Plane 1"),
                                        note=inspect_actions.SECTION_NOTE))
    for text in dialog.labels():
        assert_plain(text)
    actions = inspect_actions.InspectActions
    for text in (actions.SECTION_NEEDS_PARTS, actions.SECTION_ON, actions.SECTION_OFF,
                 *(t.tip for t in TOOLS if t.menu == "inspect")):
        assert_plain(text)
