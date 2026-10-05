"""Hardware holes: the dimension table, the geometry, and the menu."""

import re
from pathlib import Path

import numpy as np
import pytest

from mesh import hardware
from mesh.ops import evaluate
from mesh.scene import DEFAULT_FIT_CLEARANCES, new_primitive
from mesh.shapes import PRIMITIVES, primitive_mesh, shape_geometry

CLEAR = dict(DEFAULT_FIT_CLEARANCES)


def size_of(tm):
    return tm.bounds[1] - tm.bounds[0]


def test_every_size_has_every_dimension():
    for size in hardware.SCREW_SIZES:
        for part in ("clearance", "countersink", "counterbore", "nut"):
            assert (part, size) in hardware.TABLE
    for size in hardware.INSERT_SIZES:
        assert ("insert", size) in hardware.TABLE
    for key in hardware.MAGNET_PRESETS:
        assert ("magnet", key) in hardware.TABLE
    for row in hardware.TABLE.values():
        assert all(v > 0 for v in row.values())


def test_iso_273_medium_clearance_values():
    expected = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6}
    for size, diameter in expected.items():
        assert hardware.dim("clearance", size, "diameter") == diameter


def test_iso_4032_nut_values():
    flats = {"M2": 4.0, "M2.5": 5.0, "M3": 5.5, "M4": 7.0, "M5": 8.0, "M6": 10.0}
    height = {"M2": 1.6, "M2.5": 2.0, "M3": 2.4, "M4": 3.2, "M5": 4.7, "M6": 5.2}
    for size in flats:
        assert hardware.dim("nut", size, "flats") == flats[size]
        assert hardware.dim("nut", size, "depth") == height[size]


def test_magnet_presets_are_the_requested_sizes():
    sizes = [(hardware.dim("magnet", k, "diameter"), hardware.dim("magnet", k, "depth"))
             for k in hardware.MAGNET_PRESETS]
    assert sizes == [(10.0, 2.0), (8.0, 2.0), (6.0, 2.0), (4.0, 2.0)]


def test_uncertain_values_are_marked_verify():
    source = (Path(hardware.__file__)).read_text()
    for line in source.splitlines():
        if re.match(r'\s*\("(insert|counterbore)",', line):
            assert "# verify" in line, line


@pytest.mark.parametrize("size", hardware.SCREW_SIZES)
@pytest.mark.parametrize("head", ["plain", "countersunk", "counterbored"])
@pytest.mark.parametrize("clearance", [0.0, 0.2])
def test_every_screw_hole_is_watertight(size, head, clearance):
    tm = primitive_mesh("screw_hole", {"size": size, "head": head, "depth": 12.0}, clearance)
    assert tm.is_watertight
    assert tm.volume > 0
    assert np.isclose(tm.bounds[0][2], -clearance, atol=1e-5)
    assert np.isclose(tm.bounds[1][2], 12.0 + clearance, atol=1e-5)


def test_plain_m3_screw_hole_is_the_iso_size():
    tm = primitive_mesh("screw_hole", {"size": "M3", "head": "plain", "depth": 10.0})
    assert np.allclose(size_of(tm)[:2], (3.4, 3.4), atol=1e-4)
    assert np.isclose(tm.volume, np.pi * 1.7**2 * 10.0, rtol=3e-3)


def test_countersunk_top_matches_the_table_and_grows_with_fit():
    tm = primitive_mesh("screw_hole", {"size": "M4", "head": "countersunk", "depth": 10.0})
    assert np.isclose(size_of(tm)[0], 9.4, atol=1e-4)
    snug = primitive_mesh("screw_hole", {"size": "M4", "head": "countersunk", "depth": 10.0}, 0.2)
    # 0.2 on every side, and the 45-degree cone carries on 0.2 mm higher.
    assert np.isclose(size_of(snug)[0], 9.4 + 0.4 + 0.4, atol=1e-4)


def test_counterbore_recess_is_the_head_size_and_depth():
    tm = primitive_mesh("screw_hole", {"size": "M3", "head": "counterbored", "depth": 10.0})
    r_bore, r_head = 1.7, 3.25
    expected = np.pi * r_bore**2 * 7.0 + np.pi * r_head**2 * 3.0
    assert np.isclose(tm.volume, expected, rtol=3e-3)
    assert np.isclose(size_of(tm)[0], 6.5, atol=1e-4)


@pytest.mark.parametrize("size", hardware.SCREW_SIZES)
def test_nut_trap_is_a_hex_of_the_nut_size(size):
    tm = primitive_mesh("nut_trap", {"size": size, "depth": 10.0})
    assert tm.is_watertight
    flats = hardware.dim("nut", size, "flats")
    nut_h = hardware.dim("nut", size, "depth")
    bore_r = hardware.dim("clearance", size, "diameter") / 2.0
    assert np.isclose(size_of(tm)[1], flats, atol=1e-4)  # across the flats
    hex_area = flats**2 * np.sqrt(3) / 2.0
    expected = hex_area * nut_h + np.pi * bore_r**2 * (10.0 - nut_h)
    assert np.isclose(tm.volume, expected, rtol=3e-3)


@pytest.mark.parametrize("size", hardware.INSERT_SIZES)
def test_insert_pockets_are_watertight_and_sized(size):
    tm = primitive_mesh("insert_pocket", {"size": size})
    assert tm.is_watertight
    d = hardware.dim("insert", size, "diameter")
    depth = hardware.dim("insert", size, "depth")
    assert np.allclose(size_of(tm), (d, d, depth), atol=1e-4)


@pytest.mark.parametrize("key", hardware.MAGNET_PRESETS)
def test_magnet_pockets_are_watertight_and_grow_with_fit(key):
    d = hardware.dim("magnet", key, "diameter")
    tm = primitive_mesh("magnet_pocket", {"diameter": d, "depth": 2.0}, 0.1)
    assert tm.is_watertight
    assert np.allclose(size_of(tm), (d + 0.2, d + 0.2, 2.2), atol=1e-4)


def test_menu_covers_every_requested_preset():
    menu = dict(hardware.menu_presets())
    for head in ("plain", "countersunk", "counterbored"):
        items = menu[f"Screw hole ({head})"]
        assert [label for label, _k, _p in items] == list(hardware.SCREW_SIZES)
    assert [label for label, _k, _p in menu["Nut trap"]] == ["M2", "M2.5", "M3", "M4", "M5", "M6"]
    assert [label for label, _k, _p in menu["Heat-set insert pocket"]] == ["M2", "M2.5", "M3", "M4", "M5"]
    assert len(menu["Magnet pocket"]) == 4


def test_hardware_primitives_are_off_the_shelf_but_in_the_catalogue():
    from mesh.shapes import shelf_primitives

    for kind in ("screw_hole", "nut_trap", "insert_pocket", "magnet_pocket"):
        assert kind in PRIMITIVES
        assert kind not in shelf_primitives()


def test_a_screw_hole_cuts_a_block_cleanly():
    block = new_primitive("cube")
    block.params.update(width=20.0, depth=20.0, height=10.0)
    hole = new_primitive("screw_hole")
    hole.params.update(size="M3", head="countersunk", depth=10.0)
    hole.is_hole = True
    result = evaluate([block, hole], clearances=CLEAR)
    assert result.is_watertight
    assert np.isclose(result.volume, 4000.0 - shape_geometry(hole).volume, rtol=1e-3)


# --- GUI ---------------------------------------------------------------


@pytest.fixture
def window(qapp, close_qt_widget):
    from mesh.app import MeshWindow

    return close_qt_widget(MeshWindow())


def test_add_hardware_adds_one_selected_hole_as_one_undo_step(window):
    depth = len(window.document._undo)
    window.add_hardware("nut_trap", {"size": "M4"})
    scene = window.document.scene
    assert len(scene.shapes) == 1
    shape = scene.shapes[0]
    assert shape.is_hole is True
    assert shape.fit == "snug"
    assert shape.params["size"] == "M4"
    assert shape.name == "M4 nut trap"
    assert scene.selection == [shape.id]
    assert len(window.document._undo) == depth + 1
    window.do_undo()
    assert scene is not window.document.scene and window.document.scene.shapes == []


def test_every_hardware_menu_item_adds_a_watertight_hole(window):
    actions = []
    for submenu in window.hardware_menu.actions():
        actions.extend(submenu.menu().actions())
    assert len(actions) == 18 + 6 + 5 + 4
    for action in actions:
        before = len(window.document.scene.shapes)
        action.trigger()
        assert len(window.document.scene.shapes) == before + 1
        shape = window.document.scene.shapes[-1]
        assert shape.is_hole
        assert shape_geometry(shape, window.document.scene.fit_clearances).is_watertight


def test_a_hardware_hole_moves_as_one_shape(window):
    window.add_hardware("screw_hole", {"size": "M3", "head": "counterbored"})
    shape = window.document.scene.shapes[0]
    window._on_edited(shape.id, "x", 15.0)
    window._finish_edit()
    tm = shape_geometry(shape)
    assert np.isclose(tm.bounds.mean(axis=0)[0], 15.0, atol=1e-6)
    assert len(window.document.scene.shapes) == 1


def test_inspector_offers_size_and_head_choices(window):
    window.add_hardware("screw_hole", {"size": "M3", "head": "plain"})
    inspector = window.inspector
    assert inspector.visible_param_fields() == {"size", "head", "depth"}
    combo = inspector.choice_boxes["size"]
    assert [combo.itemData(i) for i in range(combo.count())] == list(hardware.SCREW_SIZES)
    assert inspector.field_value("head") == "plain"


def test_changing_the_screw_size_in_the_inspector_changes_the_hole(window):
    window.add_hardware("screw_hole", {"size": "M3", "head": "plain"})
    shape = window.document.scene.shapes[0]
    combo = window.inspector.choice_boxes["size"]
    combo.setCurrentIndex(combo.findData("M6"))
    window._finish_edit()
    assert shape.params["size"] == "M6"
    assert np.isclose(size_of(shape_geometry(shape))[0], 6.6, atol=1e-4)


def test_insert_pocket_inspector_lists_only_insert_sizes(window):
    window.add_hardware("insert_pocket", {"size": "M5"})
    combo = window.inspector.choice_boxes["size"]
    assert [combo.itemData(i) for i in range(combo.count())] == list(hardware.INSERT_SIZES)
    assert window.inspector.field_value("size") == "M5"
