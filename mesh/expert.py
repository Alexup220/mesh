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

TOOLS: tuple[ExpertTool, ...] = ()


def tools_in(menu: str) -> list[ExpertTool]:
    return [tool for tool in TOOLS if tool.menu == menu]
