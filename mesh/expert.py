"""Expert mode: the larger set of modeling tools, listed in one place.

Expert mode is a preference of this computer (mesh.settings), off on a
fresh install, and never stored in a project. With it off, none of the
tools below appear anywhere and mesh looks and behaves exactly as it does
without them. Turning it off only hides tools: shapes made with them are
ordinary shapes, so they stay in the scene, visible and editable.

Every expert tool is one ExpertTool in TOOLS. The window makes one menu
item from each entry, under its menu in MENUS, and shows or hides all of
them together when the mode changes. Listing a tool here is the only step
that puts it behind the switch.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpertTool:
    key: str          # unique id, e.g. "extrude"
    menu: str         # a key of MENUS
    label: str        # menu text, plain words ("&" marks the shortcut letter)
    tip: str          # tooltip: what it does, and what it can't do exactly
    handler: str      # the MeshWindow method the menu item calls
    shortcut: str | None = None


# The expert menus, in menu bar order: (key, title).
MENUS: tuple[tuple[str, str], ...] = (
    ("sketch", "S&ketch"),
    ("create", "&Create"),
    ("modify", "Mo&dify"),
    ("construct", "C&onstruct"),
    ("inspect", "&Inspect"),
)

TOOLS: tuple[ExpertTool, ...] = (
    ExpertTool(
        "new_sketch", "sketch", "&New Sketch...",
        "Draw a flat sketch on the workplane or an upright plane: lines, rectangles, "
        "circles, arcs, polygons and splines, placed by typed millimetres or by clicking. "
        "A sketch is a guide and is never printed; its closed outlines make parts.",
        "do_new_sketch",
    ),
    ExpertTool(
        "sketch_on_face", "sketch", "Sketch on a &Face",
        "Click a flat face of a part to draw a sketch on it. The face's outline is shown "
        "and can be copied in to trace.",
        "do_sketch_on_face",
    ),
    ExpertTool(
        "edit_sketch", "sketch", "&Change Sketch...",
        "Change the curves of the selected sketch, or of the sketch a part was made from.",
        "do_edit_sketch",
    ),
    ExpertTool(
        "extrude", "create", "&Extrude...",
        "Push the selected sketch's closed outlines straight out of its plane, into a "
        "new part or a hole. The distance stays editable in the Details panel.",
        "do_extrude", "E",
    ),
    ExpertTool(
        "revolve", "create", "&Revolve...",
        "Turn the selected sketch's closed outlines around a line, like a lathe, into a "
        "new part or a hole. Round surfaces are narrow flat strips, as on a cylinder.",
        "do_revolve",
    ),
    ExpertTool(
        "sweep", "create", "&Sweep...",
        "Carry one sketch's closed outlines along a path drawn in another sketch, into a "
        "new part or a hole. Select both sketches first. Curved paths are followed in "
        "short straight steps.",
        "do_sweep",
    ),
    ExpertTool(
        "loft", "create", "&Loft...",
        "Join two or more sketches' outlines, in the order picked, with a skin into a new "
        "part or a hole. Each needs one closed outline with no holes; the sides run "
        "straight from one outline to the next.",
        "do_loft",
    ),
    ExpertTool(
        "move_copy", "modify", "&Move or Copy...",
        "Move or turn the selected parts by exact amounts, or make moved copies of them. "
        "A turn goes around a line through their middle.",
        "do_move_copy",
    ),
    ExpertTool(
        "align_faces", "modify", "&Align Face to Face",
        "Click a flat face of the part to move, then a face of another part: the first "
        "part turns and moves so the two faces touch, facing each other, middle to middle.",
        "do_align_faces",
    ),
    ExpertTool(
        "scale", "modify", "&Scale...",
        "Make the selected parts bigger or smaller by a percentage, the same in every "
        "direction or stretched in one. Sizes stay editable. A round part stretches alike "
        "across it, roundings and bottom chamfers keep their size when stretched, and "
        "hardware holes keep their standard sizes.",
        "do_scale",
    ),
    ExpertTool(
        "combine", "modify", "&Combine...",
        "Join the other selected parts to one of them, cut them out of it, or keep only "
        "where they overlap, choosing which part to change and whether to keep the others. "
        "Ungroup gives the parts back.",
        "do_combine",
    ),
    ExpertTool(
        "split_body", "modify", "Split &Body...",
        "Split a part where it stands: select it and a sketch to cut it along the sketch's "
        "plane, or another part to cut it into the piece inside that part and the piece "
        "outside. Ungroup on a piece gives the part back.",
        "do_split_body",
    ),
    ExpertTool(
        "shell", "modify", "S&hell",
        "Click a flat face of a part to hollow it out with walls of an even thickness, "
        "leaving that face open (and, if you like, the face across from it). Exact for "
        "boxes and cylinders through their flat sides and ends; other parts are shelled "
        "approximately, and their walls can come out a little thinner in places.",
        "do_shell",
    ),
    ExpertTool(
        "push_pull", "modify", "&Push/Pull a Face",
        "Click a flat face of a part, then type how far to pull it out or push it in. The "
        "face moves straight out, square to itself; sloping sides next to it are not "
        "extended, and on a round surface only the narrow flat strip clicked moves.",
        "do_push_pull", "Q",
    ),
    ExpertTool(
        "fillet", "modify", "&Round an Edge (Fillet)",
        "Click a face of a part next to an edge, then type the radius. The edge is rounded "
        "along with the edges it runs on into smoothly; an inside edge is filled in round. "
        "Round surfaces are narrow flat strips, and corners where rounded edges meet are "
        "not blended into a ball.",
        "do_fillet",
    ),
)


def tools_in(menu: str) -> list[ExpertTool]:
    return [tool for tool in TOOLS if tool.menu == menu]
