"""What the window's ribbon, tool palette and Insert panel hold, as data.

Every command the window has is one menu item (a QAction on the main
window). The QML front end names each one by a key made from its menu and
its text, e.g. "shape.group" or "create.extrude" (see command_key), and
this module says where those keys appear: which ribbon tab and group, which
icon, and which shapes the Insert panel offers. Keeping it here, free of
Qt, lets the tests check that every command has an icon and a place.
"""

import re

from mesh import hardware
from mesh.shapes import PRIMITIVES, shelf_primitives


def slug(text: str) -> str:
    """Menu text as a key part: "Hollow &Out..." -> "hollow_out"."""
    text = text.replace("&", "").replace("...", "").replace("×", "x")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def command_key(menu_path: list[str], text: str) -> str:
    """The key of the menu item `text` under the menus `menu_path` (the
    top menu first): "shape.group", "add_hardware_hole.nut_trap.m3"."""
    return ".".join([slug(part) for part in menu_path] + [slug(text)])


# --- icons ---------------------------------------------------------------

# The icon (a file in mesh/assets/icons, without ".svg") of each command.
ICONS: dict[str, str] = {
    "file.open_project": "open",
    "file.save_project": "save",
    "file.add_a_model_file": "import",
    "file.save_for_printing": "export",
    "file.quit": "quit",
    "edit.undo": "undo",
    "edit.redo": "redo",
    "edit.stop_current_tool": "stop",
    "edit.duplicate": "duplicate",
    "edit.delete": "delete",
    "edit.select_all": "select_all",
    "shape.group": "group",
    "shape.ungroup": "ungroup",
    "shape.make_hole_solid": "hole",
    "shape.fit_clearances": "fit",
    "shape.lay_flat_on_a_face": "lay_flat",
    "shape.place_next_shape_on_a_face": "place",
    "shape.hollow_out": "hollow",
    "shape.split_part": "split",
    "shape.repeat_in_a_row": "repeat_row",
    "shape.repeat_in_a_circle": "repeat_circle",
    "shape.box_with_lid": "box_lid",
    "shape.add_text": "text",
    "shape.join": "join",
    "shape.cut_out": "cut",
    "shape.keep_overlap": "overlap",
    "shape.mirror_along_x": "mirror_x",
    "shape.mirror_along_y": "mirror_y",
    "shape.mirror_along_z": "mirror_z",
    "tools.measure": "measure",
    "tools.expert_mode": "expert",
    "sketch.new_sketch": "sketch_new",
    "sketch.sketch_on_a_face": "sketch_face",
    "sketch.change_sketch": "sketch_edit",
    "create.extrude": "extrude",
    "create.revolve": "revolve",
    "create.sweep": "sweep",
    "create.loft": "loft",
    "create.pattern_in_rows_rectangular": "pattern_rect",
    "create.pattern_around_a_line_circular": "pattern_circ",
    "create.pattern_along_a_path": "pattern_path",
    "create.mirror": "mirror_body",
    "create.thread": "thread",
    "create.pipe": "pipe",
    "create.coil": "coil",
    "modify.move_or_copy": "move_copy",
    "modify.align_face_to_face": "align_faces",
    "modify.scale": "scale",
    "modify.combine": "combine",
    "modify.split_body": "split_body",
    "modify.shell": "shell",
    "modify.push_pull_a_face": "push_pull",
    "modify.round_an_edge_fillet": "fillet",
    "modify.bevel_an_edge_chamfer": "chamfer",
    "modify.slope_the_sides_draft": "draft",
    "modify.change_parameters": "parameters",
    "modify.link_sizes_to_parameters": "link_params",
    "modify.history": "history",
    "assemble.new_component_from_selection": "component_new",
    "assemble.select_whole_component": "component_select",
    "assemble.take_out_of_component": "component_out",
    "assemble.components": "components",
    "construct.plane_at_a_distance": "plane_distance",
    "construct.plane_at_an_angle": "plane_angle",
    "construct.plane_halfway_between_midplane": "plane_mid",
    "construct.plane_through_three_points": "plane_3pt",
    "construct.plane_touching_a_round_part": "plane_tangent",
    "construct.plane_along_a_path": "plane_path",
    "construct.axis_through_a_round_part": "axis_round",
    "construct.axis_through_two_points": "axis_2pt",
    "construct.axis_square_to_a_face": "axis_face",
    "construct.axis_along_an_edge": "axis_edge",
    "construct.axis_where_two_planes_meet": "axis_planes",
    "construct.point_at_a_click": "point_click",
    "construct.point_at_the_middle_of_a_face": "point_face",
    "construct.point_at_the_end_of_an_edge": "point_edge",
    "construct.point_where_three_planes_meet": "point_planes",
    "construct.point_where_an_axis_meets_a_plane": "point_axis",
    "inspect.section_view": "section",
    "inspect.measure_between_faces": "measure_faces",
    "inspect.radius_of_a_round_face": "radius",
    "inspect.length_of_an_edge": "edge_length",
    "inspect.volume_and_area": "volume",
    "inspect.shortest_distance_between_parts": "part_distance",
    "view.home": "view_home",
    "view.front": "view_front",
    "view.right": "view_right",
    "view.top": "view_top",
    "view.zoom_to_selection": "zoom_selection",
    # Added by the QML window to its View menu.
    "view.search_commands": "search",
    "view.theme_editor": "theme_editor",
    "view.welcome_screen": "welcome",
}

for _axis in "xyz":
    for _mode in ("min", "center", "max"):
        ICONS[f"shape.align_{_axis}_{_mode}"] = f"align_{_mode}_{_axis}"

# Hardware holes: every size of one kind shares that kind's icon.
HARDWARE_ICONS: dict[str, str] = {
    "screw_hole_plain": "screw_plain",
    "screw_hole_countersunk": "screw_countersunk",
    "screw_hole_counterbored": "screw_counterbored",
    "nut_trap": "nut_trap",
    "heat_set_insert_pocket": "insert",
    "magnet_pocket": "magnet",
}

# Commands made from things that change (a theme's name, a panel's title)
# take their icon from the start of their key.
PREFIX_ICONS: dict[str, str] = {
    "view.theme.": "theme",
    "view.panels.": "panel",
}


def icon_for(key: str) -> str | None:
    """The icon of the command `key`, or None if it has none."""
    if key in ICONS:
        return ICONS[key]
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "add_hardware_hole":
        return HARDWARE_ICONS.get(parts[1])
    for prefix, icon in PREFIX_ICONS.items():
        if key.startswith(prefix):
            return icon
    return None


def icon_names() -> set[str]:
    """Every icon file the window needs."""
    return (set(ICONS.values()) | set(HARDWARE_ICONS.values()) | set(PREFIX_ICONS.values())
            | {"hardware", "align", "mirror", "palette_select"})


# --- the ribbon ------------------------------------------------------------

# Each tab: (title, shown only in Expert mode, groups). Each group: (title,
# items). An item is a command key, or a drop-down: ("menu", label, icon,
# the key prefix of the commands it lists).
RIBBON: tuple = (
    ("Create", False, (
        ("Make", ("shape.add_text", "shape.box_with_lid",
                  ("menu", "Hardware hole", "hardware", "add_hardware_hole."))),
        ("Sketch", ("sketch.new_sketch", "sketch.sketch_on_a_face", "sketch.change_sketch")),
        ("From a sketch", ("create.extrude", "create.revolve", "create.sweep", "create.loft",
                           "create.pipe", "create.thread", "create.coil")),
        ("Copies", ("shape.repeat_in_a_row", "shape.repeat_in_a_circle",
                    "create.pattern_in_rows_rectangular", "create.pattern_around_a_line_circular",
                    "create.pattern_along_a_path", "create.mirror")),
        ("Guides", (("menu", "Plane", "plane_distance", "construct.plane_"),
                    ("menu", "Axis", "axis_2pt", "construct.axis_"),
                    ("menu", "Point", "point_click", "construct.point_"))),
    )),
    ("Modify", False, (
        ("Edit", ("edit.undo", "edit.redo", "edit.duplicate", "edit.delete", "edit.select_all")),
        ("Combine", ("shape.group", "shape.ungroup", "shape.make_hole_solid", "shape.join",
                     "shape.cut_out", "shape.keep_overlap", "modify.combine")),
        ("Arrange", ("shape.lay_flat_on_a_face", "shape.place_next_shape_on_a_face",
                     ("menu", "Mirror", "mirror", "shape.mirror_"),
                     ("menu", "Align", "align", "shape.align_"),
                     "modify.move_or_copy", "modify.align_face_to_face")),
        ("Change", ("shape.hollow_out", "shape.split_part", "shape.fit_clearances",
                    "modify.scale", "modify.split_body", "modify.shell", "modify.push_pull_a_face",
                    "modify.round_an_edge_fillet", "modify.bevel_an_edge_chamfer",
                    "modify.slope_the_sides_draft")),
        ("Parameters", ("modify.change_parameters", "modify.link_sizes_to_parameters",
                        "modify.history")),
        ("Components", ("assemble.new_component_from_selection", "assemble.select_whole_component",
                        "assemble.take_out_of_component", "assemble.components")),
    )),
    ("Inspect", False, (
        ("Measure", ("tools.measure", "inspect.measure_between_faces", "inspect.radius_of_a_round_face",
                     "inspect.length_of_an_edge", "inspect.volume_and_area",
                     "inspect.shortest_distance_between_parts", "inspect.section_view")),
        ("View", ("view.home", "view.front", "view.right", "view.top", "view.zoom_to_selection")),
        ("Window", ("view.search_commands", "view.theme_editor", "tools.expert_mode")),
    )),
    ("Export", False, (
        ("Project", ("file.open_project", "file.save_project")),
        ("Models", ("file.add_a_model_file", "file.save_for_printing")),
    )),
)


def ribbon_keys() -> list[str]:
    """Every command key and drop-down prefix the ribbon names."""
    keys = []
    for _title, _expert, groups in RIBBON:
        for _group, items in groups:
            for item in items:
                keys.append(item[3] if isinstance(item, tuple) else item)
    return keys


# The tool palette down the left side: the click-on-a-part tools and the
# everyday edits.
PALETTE: tuple[str, ...] = (
    "edit.stop_current_tool",
    "shape.lay_flat_on_a_face",
    "shape.place_next_shape_on_a_face",
    "tools.measure",
    "shape.make_hole_solid",
    "shape.group",
    "shape.ungroup",
    "edit.duplicate",
    "edit.delete",
    "view.zoom_to_selection",
)


# --- the Insert panel --------------------------------------------------------

# Hardware holes the Insert panel offers, one per kind, at a common size
# (pick another size in the Properties panel): (insert key, label,
# primitive, params).
HARDWARE_INSERTS: tuple = (
    ("hardware:screw_plain", "Screw hole", "screw_hole", {"size": "M3", "head": "plain"}),
    ("hardware:screw_countersunk", "Countersunk screw", "screw_hole", {"size": "M3", "head": "countersunk"}),
    ("hardware:screw_counterbored", "Counterbored screw", "screw_hole", {"size": "M3", "head": "counterbored"}),
    ("hardware:nut_trap", "Nut trap", "nut_trap", {"size": "M3"}),
    ("hardware:insert", "Heat-set insert", "insert_pocket", {"size": "M3"}),
    ("hardware:magnet", "Magnet pocket", "magnet_pocket", None),
)


def _magnet_params() -> dict:
    """The first magnet preset's params, as the hardware menu has them."""
    for label, items in hardware.menu_presets():
        if items and items[0][1] == "magnet_pocket":
            return dict(items[0][2])
    raise LookupError("no magnet pocket preset")


def hardware_inserts() -> list[tuple[str, str, str, dict]]:
    return [(key, label, primitive, dict(params) if params is not None else _magnet_params())
            for key, label, primitive, params in HARDWARE_INSERTS]


def insert_items() -> list[dict]:
    """The Insert panel's thumbnails, in order: each a dict of key, label,
    thumbnail (a file in mesh/assets/thumbnails, without ".svg"), section,
    and command (the menu item it runs instead, for the ones that ask for
    numbers first)."""
    items = [
        {"key": f"shape:{kind}", "label": PRIMITIVES[kind]["label"], "thumbnail": kind,
         "section": "Shapes", "command": ""}
        for kind in shelf_primitives()
    ]
    items += [
        {"key": key, "label": label, "thumbnail": key.split(":", 1)[1], "section": "Hardware holes",
         "command": ""}
        for key, label, _primitive, _params in hardware_inserts()
    ]
    items += [
        {"key": "command:shape.add_text", "label": "Text", "thumbnail": "text",
         "section": "Ready-made", "command": "shape.add_text"},
        {"key": "command:shape.box_with_lid", "label": "Box with lid", "thumbnail": "box_lid",
         "section": "Ready-made", "command": "shape.box_with_lid"},
    ]
    return items
