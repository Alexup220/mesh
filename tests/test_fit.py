"""Fit tolerance: Holes grow by the scene's clearance on every side."""

import json

import numpy as np
import pytest
import trimesh

from mesh.blobs import encode_mesh
from mesh.io_formats import export_scene, load_project, save_project
from mesh.ops import evaluate, make_group
from mesh.printcheck import check
from mesh.scene import DEFAULT_FIT_CLEARANCES, FITS, Scene, Shape, new_primitive
from mesh.shapes import shape_geometry

CLEAR = dict(DEFAULT_FIT_CLEARANCES)


def cylinder_hole(diameter=10.0, height=10.0, fit="snug"):
    s = new_primitive("cylinder")
    s.params.update(diameter=diameter, height=height)
    s.is_hole = True
    s.fit = fit
    return s


def size_of(tm):
    return tm.bounds[1] - tm.bounds[0]


def test_default_clearances_match_the_brief():
    assert CLEAR == {"press": 0.1, "snug": 0.2, "loose": 0.4}
    assert Scene().fit_clearances == CLEAR
    assert list(FITS) == ["exact", "press", "snug", "loose"]


@pytest.mark.parametrize("fit, grow", [("exact", 0.0), ("press", 0.2), ("snug", 0.4), ("loose", 0.8)])
def test_a_10mm_hole_grows_by_twice_the_clearance(fit, grow):
    tm = shape_geometry(cylinder_hole(fit=fit), CLEAR)
    assert tm.is_watertight
    assert np.allclose(size_of(tm), (10.0 + grow, 10.0 + grow, 10.0 + grow), atol=1e-3)
    # Grows evenly: the bottom drops by one clearance.
    assert np.isclose(tm.bounds[0][2], -grow / 2.0, atol=1e-6)


def test_a_box_hole_grows_on_every_side():
    s = new_primitive("cube")
    s.params.update(width=10.0, depth=20.0, height=5.0)
    s.is_hole, s.fit = True, "snug"
    s.transform[:3, 3] = [3.0, 4.0, 0.0]
    tm = shape_geometry(s, CLEAR)
    assert np.allclose(tm.bounds, [[-2.2, -6.2, -0.2], [8.2, 14.2, 5.2]], atol=1e-6)


def test_fit_is_ignored_without_clearances_or_on_a_solid():
    hole = cylinder_hole()
    assert np.allclose(size_of(shape_geometry(hole)), (10.0, 10.0, 10.0), atol=1e-3)
    solid = cylinder_hole()
    solid.is_hole = False
    assert np.allclose(size_of(shape_geometry(solid, CLEAR)), (10.0, 10.0, 10.0), atol=1e-3)


def test_tube_hole_wall_grows_so_its_inside_shrinks():
    s = new_primitive("tube")
    s.params.update(diameter=20.0, wall=2.0, height=10.0)
    s.is_hole, s.fit = True, "loose"
    tm = shape_geometry(s, CLEAR)
    assert tm.is_watertight
    outer_r, inner_r = 10.4, 10.0 - 2.0 - 0.4
    expected = np.pi * (outer_r**2 - inner_r**2) * 10.8
    assert np.isclose(tm.volume, expected, rtol=5e-3)


def test_imported_hole_grows_by_twice_the_clearance_per_axis():
    s = Shape(id="i", name="imp", kind="imported",
              params={"blob": encode_mesh(trimesh.creation.box(extents=(10.0, 6.0, 4.0)))},
              transform=np.eye(4), is_hole=True, fit="loose")
    tm = shape_geometry(s, CLEAR)
    assert tm.is_watertight
    assert np.allclose(size_of(tm), (10.8, 6.8, 4.8), atol=1e-6)


def _block_with_hole(fit):
    block = new_primitive("cube")
    block.params.update(width=30.0, depth=30.0, height=10.0)
    hole = cylinder_hole(diameter=10.0, height=20.0, fit=fit)
    hole.transform[2, 3] = -5.0
    return block, hole


def test_evaluate_cuts_the_fitted_size():
    block, hole = _block_with_hole("snug")
    result = evaluate([block, hole], clearances=CLEAR)
    assert result.is_watertight
    r = 5.2
    assert np.isclose(result.volume, 9000.0 - np.pi * r * r * 10.0, rtol=2e-3)


def test_group_and_export_and_status_agree(tmp_path):
    block, hole = _block_with_hole("loose")
    scene = Scene(shapes=[block, hole])
    expected = 9000.0 - np.pi * 5.4**2 * 10.0

    group = make_group([block, hole], clearances=scene.fit_clearances)
    assert np.isclose(shape_geometry(group).volume, expected, rtol=2e-3)

    path = tmp_path / "part.stl"
    export_scene(scene, path)
    assert np.isclose(trimesh.load(path).volume, expected, rtol=2e-3)

    assert np.isclose(check(scene).volume_mm3, expected, rtol=2e-3)


def test_custom_clearances_are_used():
    block, hole = _block_with_hole("snug")
    scene = Scene(shapes=[block, hole])
    scene.fit_clearances["snug"] = 0.5
    assert np.isclose(check(scene).volume_mm3, 9000.0 - np.pi * 5.5**2 * 10.0, rtol=2e-3)


def test_fit_and_clearances_round_trip_through_a_project(tmp_path):
    scene = Scene(shapes=[cylinder_hole(fit="press")])
    scene.fit_clearances["loose"] = 0.6
    path = tmp_path / "p.mesh"
    save_project(scene, path)
    loaded = load_project(path)
    assert loaded.shapes[0].fit == "press"
    assert loaded.fit_clearances == {"press": 0.1, "snug": 0.2, "loose": 0.6}


def test_a_project_saved_before_fits_existed_still_loads(tmp_path):
    """Exactly the shape of a .mesh file written by the original build:
    no "fit" on shapes and no "fit_clearances" on the scene."""
    old = {
        "format_version": 1,
        "scene": {
            "shapes": [{
                "id": "abc", "name": "Cylinder", "kind": "primitive",
                "params": {"diameter": 10.0, "height": 10.0, "primitive": "cylinder"},
                "transform": np.eye(4).tolist(), "color": "#4a90d9",
                "is_hole": True, "visible": True,
            }],
            "selection": ["abc"],
            "build_volume": [220.0, 220.0, 250.0],
            "snap_mm": 1.0,
        },
    }
    path = tmp_path / "old.mesh"
    path.write_text(json.dumps(old))
    scene = load_project(path)
    shape = scene.shapes[0]
    assert shape.fit == "exact"
    assert scene.fit_clearances == CLEAR
    assert np.allclose(size_of(shape_geometry(shape, scene.fit_clearances)), (10, 10, 10), atol=1e-3)


def test_an_unknown_fit_in_a_file_falls_back_to_exact():
    d = cylinder_hole().to_dict()
    d["fit"] = "wobbly"
    assert Shape.from_dict(d).fit == "exact"


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


@pytest.fixture
def inspector(qapp, close_qt_widget):
    from mesh.panels import Inspector

    return close_qt_widget(Inspector())


def test_inspector_shows_fit_only_for_holes(inspector):
    solid = new_primitive("cube")
    inspector.show_shape(solid)
    assert inspector._layout.isRowVisible(inspector._fit_row) is False
    hole = cylinder_hole(fit="loose")
    inspector.show_shape(hole)
    assert inspector._layout.isRowVisible(inspector._fit_row) is True
    assert inspector.field_value("fit") == "loose"


def test_inspector_fit_choice_emits_an_edit(inspector):
    hole = cylinder_hole(fit="exact")
    inspector.show_shape(hole)
    seen = []
    inspector.edited.connect(lambda *a: seen.append(a))
    inspector.fit_box.setCurrentIndex(inspector.fit_box.findData("snug"))
    assert (hole.id, "fit", "snug") in seen


def test_fit_labels_are_plain_language(inspector):
    labels = [inspector.fit_box.itemText(i) for i in range(inspector.fit_box.count())]
    assert labels == ["Exact", "Press fit", "Snug fit", "Loose fit"]


def test_editing_fit_is_one_undo_step(window):
    window.add_primitive("cylinder")
    shape = window.document.scene.shapes[0]
    window._on_edited(shape.id, "is_hole", True)
    window._on_edited(shape.id, "fit", "snug")
    window._finish_edit()
    assert shape.fit == "snug"
    depth = len(window.document._undo)
    window._on_edited(shape.id, "fit", "loose")
    window._finish_edit()
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert window.document.scene.get(shape.id).fit == "snug"


def test_viewport_shows_the_fitted_size(window):
    window.add_primitive("cylinder")
    shape = window.document.scene.shapes[0]
    shape.is_hole, shape.fit = True, "loose"
    window.sync()
    bounds = window.viewport.actor_for(shape.id).GetMapper().GetInput().GetBounds()
    assert np.isclose(bounds[1] - bounds[0], 20.8, atol=1e-3)


def test_set_fit_clearances_is_one_undo_step_and_rebuilds_the_view(window):
    window.add_primitive("cylinder")
    shape = window.document.scene.shapes[0]
    shape.is_hole, shape.fit = True, "snug"
    window.sync()
    depth = len(window.document._undo)
    assert window.set_fit_clearances({"snug": 0.5}) is True
    assert len(window.document._undo) == depth + 1
    assert window.document.scene.fit_clearances["snug"] == 0.5
    bounds = window.viewport.actor_for(shape.id).GetMapper().GetInput().GetBounds()
    assert np.isclose(bounds[1] - bounds[0], 21.0, atol=1e-3)
    window.do_undo()
    assert window.document.scene.fit_clearances["snug"] == 0.2


def test_bad_fit_clearance_is_refused_without_an_undo_step(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    depth = len(window.document._undo)
    assert window.set_fit_clearances({"snug": -1.0}) is False
    assert window.set_fit_clearances(dict(CLEAR)) is False  # nothing changed
    assert len(window.document._undo) == depth
    assert len(warnings) == 1


def test_group_in_the_window_uses_the_fitted_size(window):
    block, hole = _block_with_hole("snug")
    window.document.scene.add(block)
    window.document.scene.add(hole)
    window.document.scene.select([block.id, hole.id])
    window.do_group()
    group = window.document.scene.shapes[0]
    assert np.isclose(shape_geometry(group).volume, 9000.0 - np.pi * 5.2**2 * 10.0, rtol=2e-3)


def test_fit_clearance_dialog_reads_back_its_values(qapp, close_qt_widget):
    from mesh.panels import FormDialog, fit_clearance_fields

    dialog = close_qt_widget(FormDialog(None, "Fit clearances", fit_clearance_fields(CLEAR)))
    assert dialog.values() == CLEAR
