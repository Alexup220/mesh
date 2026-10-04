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
)


def tools_in(menu: str) -> list[ExpertTool]:
    return [tool for tool in TOOLS if tool.menu == menu]
