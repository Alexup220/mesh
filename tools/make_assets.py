"""Draw the window's icons and the Insert panel's thumbnails.

    uv run python tools/make_assets.py

Icons (mesh/assets/icons/*.svg) are small line drawings, written out here
by hand. They use two colours, INK and ACCENT, which the window swaps for
the theme's text and highlight colours when it shows them.

Thumbnails (mesh/assets/thumbnails/*.svg) are drawn from each shape's real
geometry: the same triangles the 3D view shows, seen from the 3D view's
home angle and shaded flat. Nothing is downloaded.

Run it again after adding a command or a shape; the tests check that every
command has an icon and every Insert item a thumbnail.
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mesh import builders, panels, ui_catalog  # noqa: E402
from mesh.bridge import ICON_ACCENT as A, ICON_INK as I  # noqa: E402
from mesh.scene import DEFAULT_COLOR, new_primitive  # noqa: E402
from mesh.shapes import PRIMITIVES, shape_geometry  # noqa: E402

ICON_DIR = ROOT / "mesh" / "assets" / "icons"
THUMBNAIL_DIR = ROOT / "mesh" / "assets" / "thumbnails"

# --- icons -------------------------------------------------------------------


def p(d, color=I, fill="none", width=1.6, extra=""):
    return (f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{extra}/>')


def acc(d, fill="none", width=1.6, extra=""):
    return p(d, A, fill, width, extra)


def dashed(d, color=A, width=1.6):
    return p(d, color, extra=' stroke-dasharray="2.2 2"', width=width)


def dot(x, y, r=1.6, color=A):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'


def circle(x, y, r, color=I, fill="none", width=1.6, extra=""):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{color}" stroke-width="{width}"{extra}/>'


def g(transform, *parts):
    return f'<g transform="{transform}">' + "".join(parts) + "</g>"


CUBE = "M12 3 L20 7.5 L20 16.5 L12 21 L4 16.5 L4 7.5 Z M4 7.5 L12 12 L20 7.5 M12 12 L12 21"
CUBE_TOP = "M12 3 L20 7.5 L12 12 L4 7.5 Z"
CUBE_FRONT = "M4 7.5 L12 12 L12 21 L4 16.5 Z"
CUBE_RIGHT = "M20 7.5 L12 12 L12 21 L20 16.5 Z"
PLANE = "M3 15 L9 9 L21 9 L15 15 Z"
LETTERS = {
    "x": "M17.5 16.5 L21.5 21.5 M21.5 16.5 L17.5 21.5",
    "y": "M17.5 16.5 L19.5 19 L21.5 16.5 M19.5 19 L19.5 21.5",
    "z": "M17.5 16.5 L21.5 16.5 L17.5 21.5 L21.5 21.5",
}


def small_cube(dx=0, dy=0, s=0.55):
    return g(f"translate({dx} {dy}) scale({s})", p(CUBE, width=1.6 / s))


def mirror(axis):
    if axis is None:
        return (p("M3 18 L9 6 L9 18 Z") + acc("M15 6 L15 18 L21 18 Z", fill=A, width=1.2)
                + dashed("M12 3 L12 21", I, 1.2))
    return (p("M2 16 L8 5 L8 16 Z") + acc("M14 5 L14 16 L20 16 Z", fill=A, width=1.2)
            + dashed("M11 2 L11 19", I, 1.2) + acc(LETTERS[axis], width=1.4))


def align(mode, axis):
    bars = {
        "min": "M5 6 L13 6 M5 11 L18 11 M5 16 L10 16",
        "center": "M7 6 L15 6 M4.5 11 L17.5 11 M8.5 16 L13.5 16",
        "max": "M8 6 L16 6 M3 11 L16 11 M11 16 L16 16",
    }[mode]
    guide = {"min": "M4 3 L4 19", "center": "M11 3 L11 19", "max": "M17 3 L17 19"}[mode]
    out = p(bars, width=2.6) + acc(guide, width=1.4)
    if axis:
        out += acc(LETTERS[axis], width=1.4)
    return out


def view(face):
    return p(CUBE) + acc(face, fill=A, width=1.2, extra=' fill-opacity="0.55"')


def plane_icon(extra):
    return p(PLANE) + extra


ICONS = {
    "open": p("M3 7 L3 19 L19 19 L21 10 L8 10 L6 19 M3 7 L3 5 L9 5 L11 7 L18 7 L18 10"),
    "save": p("M4 4 L17 4 L20 7 L20 20 L4 20 Z M8 4 L8 9 L15 9 L15 4") + acc("M8 20 L8 14 L16 14 L16 20"),
    "import": p("M4 14 L4 20 L20 20 L20 14") + acc("M12 3 L12 15 M7.5 10.5 L12 15 L16.5 10.5"),
    "export": p("M4 14 L4 20 L20 20 L20 14") + acc("M12 15 L12 3 M7.5 7.5 L12 3 L16.5 7.5"),
    "quit": p("M10 4 L4 4 L4 20 L10 20") + acc("M10 12 L21 12 M17 8 L21 12 L17 16"),
    "undo": p("M9 14 L4 9 L9 4") + acc("M4 9 L14 9 A6 6 0 0 1 14 21 L9 21"),
    "redo": p("M15 14 L20 9 L15 4") + acc("M20 9 L10 9 A6 6 0 0 0 10 21 L15 21"),
    "stop": circle(12, 12, 9) + acc("M8.5 8.5 L15.5 8.5 L15.5 15.5 L8.5 15.5 Z", fill=A),
    "duplicate": p("M8 8 L20 8 L20 20 L8 20 Z") + acc("M4 16 L4 4 L16 4"),
    "delete": p("M4 6 L20 6 M9 6 L9 3.5 L15 3.5 L15 6 M6 6 L7 21 L17 21 L18 6") + acc("M10 10 L10 17 M14 10 L14 17"),
    "select_all": dashed("M3 3 L21 3 L21 21 L3 21 Z", I, 1.4) + acc("M8 8 L16 8 L16 16 L8 16 Z", fill=A),
    "group": dashed("M2.5 2.5 L21.5 2.5 L21.5 21.5 L2.5 21.5 Z", I, 1.2) + p("M6 9 L13 9 L13 18 L6 18 Z")
    + acc("M10 6 L18 6 L18 14 L10 14 Z"),
    "ungroup": p("M3 10 L10 10 L10 20 L3 20 Z") + acc("M14 4 L21 4 L21 12 L14 12 Z") + dashed("M10 10 L14 12", I, 1.2),
    "hole": p("M3 6 L21 6 L21 20 L3 20 Z") + dashed("M8 9 L16 9 L16 17 L8 17 Z"),
    "fit": circle(12, 12, 9) + circle(12, 12, 5, A) + acc("M12 3 L12 7 M12 17 L12 21", width=1.2),
    "lay_flat": g("translate(4 0) scale(0.66)", p(CUBE, width=2.4)) + p("M3 21 L21 21") + acc("M4 9 L4 18 M2 15.5 L4 18 L6 15.5"),
    "place": p(PLANE) + small_cube(5.4, 0.2, 0.55) + dot(12, 12, 1.8),
    "hollow": p(CUBE) + dashed("M12 7.5 L16 9.8 L16 14.3 L12 16.5 L8 14.3 L8 9.8 Z"),
    "split": p("M4 4 L20 4 L20 20 L4 20 Z") + acc("M2 12 L22 12", width=2) + acc("M7 9 L7 12 M17 12 L17 15", width=1.2),
    "repeat_row": p("M2 9 L7 9 L7 15 L2 15 Z") + acc("M9.5 9 L14.5 9 L14.5 15 L9.5 15 Z") + acc("M17 9 L22 9 L22 15 L17 15 Z"),
    "repeat_circle": circle(12, 12, 7.5, I, extra=' stroke-dasharray="2 2"') + dot(12, 4.5, 2.3, I)
    + dot(19.5, 12, 2.3) + dot(12, 19.5, 2.3) + dot(4.5, 12, 2.3),
    "box_lid": p("M4 12 L20 12 L20 21 L4 21 Z") + acc("M3 5 L21 5 L21 9 L3 9 Z"),
    "text": p("M5 5 L19 5 M12 5 L12 20 M9 20 L15 20") + acc("M5 5 L5 7.5 M19 5 L19 7.5"),
    "join": acc("M9 4 A7 7 0 1 0 9 18 A7 7 0 0 0 15 20 A7 7 0 1 0 9 4 Z", fill=A, width=1.4,
                extra=' fill-opacity="0.35"') + circle(9, 11, 7) + circle(15, 13, 7),
    "cut": circle(10, 12, 7.5) + dashed("M16 7 A6 6 0 1 1 16 19 A6 6 0 0 1 16 7 Z"),
    "overlap": circle(9, 12, 7) + circle(15, 12, 7) + acc("M12 5.7 A7 7 0 0 1 12 18.3 A7 7 0 0 1 12 5.7 Z", fill=A),
    "measure": p("M3 15 L15 3 L21 9 L9 21 Z") + acc("M7 11 L9 13 M10 8 L12 10 M13 5 L15 7"),
    "expert": acc("M12 3 L14.6 8.8 L21 9.4 L16.2 13.6 L17.6 20 L12 16.7 L6.4 20 L7.8 13.6 L3 9.4 L9.4 8.8 Z", fill=A,
                  extra=' fill-opacity="0.35"'),
    "sketch_new": p("M3 10 L13 10 L13 20 L3 20 Z") + acc("M14 13 L21 6 L18 3 L11 10 L10 14 Z"),
    "sketch_face": p("M2 17 L7 9 L22 9 L17 17 Z") + acc("M14 13 L20 5 L17.5 3 L12 10 L11.5 13.5 Z"),
    "sketch_edit": p("M3 18 C6 8 10 20 14 10") + acc("M14 13 L21 6 L18 3 L11 10 L10 14 Z"),
    "extrude": p("M4 18 L10 14 L20 14 L14 18 Z") + acc("M4 18 L4 9 L10 5 L20 5 L20 14 M4 9 L14 9 L20 5 M14 9 L14 18")
    + acc("M12 13 L12 1.5", width=1.2),
    "revolve": p("M8 4 L8 20 M8 6 L13 6 L13 10 L11 12 L11 18 L8 18") + acc("M15 15 A7 3 0 1 0 15 9 M15 9 L17.5 7.5 M15 9 L17 11"),
    "sweep": p("M3 7 L8 4 L8 9 L3 12 Z") + acc("M5.5 8 C10 8 10 18 20 18") + p("M17 15 L21 15 L21 21 L17 21 Z"),
    "loft": p("M3 18 L9 21 L15 18 L9 15 Z") + acc("M8 4 A4 2 0 1 0 16 4 A4 2 0 1 0 8 4 Z") + p("M3 18 L8 4 M15 18 L16 4", width=1.2),
    "pattern_rect": "".join(p(f"M{x} {y} h4 v4 h-4 Z") if (x, y) == (3, 4) else acc(f"M{x} {y} h4 v4 h-4 Z")
                            for x in (3, 10, 17) for y in (4, 13)),
    "pattern_circ": circle(12, 12, 1.5, A, A) + "".join(dot(12 + 7.5 * np.cos(a), 12 + 7.5 * np.sin(a), 1.9,
                                                            I if i == 0 else A)
                                                        for i, a in enumerate(np.linspace(0, 2 * np.pi, 7)[:-1])),
    "pattern_path": p("M3 19 C7 3 15 21 21 5", width=1.2) + dot(3.5, 18, 2.2, I) + dot(8.7, 10.5, 2.2) + dot(14, 13.2, 2.2)
    + dot(20.3, 6.5, 2.2),
    "mirror_body": mirror(None),
    "mirror": mirror(None),
    "mirror_x": mirror("x"),
    "mirror_y": mirror("y"),
    "mirror_z": mirror("z"),
    "align": align("min", None),
    "thread": p("M8 3 L16 3 L16 6 L8 6 Z M9.5 6 L9.5 21 L14.5 21 L14.5 6") + acc("M9.5 9 L14.5 11 M9.5 12 L14.5 14 M9.5 15 L14.5 17 M9.5 18 L14.5 20"),
    "pipe": p("M3 8 L10 8 A6 6 0 0 1 16 14 L16 21 M3 14 L10 14 A0 0 0 0 1 10 14 L10 21") + acc("M3 8 L3 14 M10 21 L16 21"),
    "coil": acc("M6 4 L18 6.5 L6 9 L18 11.5 L6 14 L18 16.5 L6 19") + p("M12 2 L12 21", width=1, extra=' stroke-dasharray="1.5 2"'),
    "move_copy": acc("M12 3 L12 21 M3 12 L21 12 M9.5 5.5 L12 3 L14.5 5.5 M9.5 18.5 L12 21 L14.5 18.5 M5.5 9.5 L3 12 L5.5 14.5 M18.5 9.5 L21 12 L18.5 14.5"),
    "align_faces": p("M2 6 L9 6 L9 18 L2 18 Z") + acc("M15 6 L22 6 L22 18 L15 18 Z") + p("M10.5 12 L13.5 12 M12 10 L13.5 12 L12 14", width=1.3),
    "scale": p("M3 13 L11 13 L11 21 L3 21 Z") + acc("M3 13 L3 3 L21 3 L21 21 L11 21 M13 11 L19 5 M15 5 L19 5 L19 9"),
    "combine": p("M3 3 L14 3 L14 14 L3 14 Z") + acc("M10 10 L21 10 L21 21 L10 21 Z", fill=A, extra=' fill-opacity="0.35"'),
    "split_body": p(CUBE) + acc("M1.5 13 L12 7 L22.5 13 L12 19 Z", width=1.3),
    "shell": p("M4 9 L4 19 L20 19 L20 9") + acc("M7 9 L7 16 L17 16 L17 9") + p("M4 9 L7 9 M17 9 L20 9"),
    "push_pull": p("M3 16 L9 12 L21 12 L15 16 Z") + acc("M12 2 L12 13 M9 5 L12 2 L15 5"),
    "fillet": p("M4 20 L4 4 M4 20 L20 20") + acc("M4 9 A11 11 0 0 0 15 20", width=2),
    "chamfer": p("M4 20 L4 4 M4 20 L20 20") + acc("M4 10 L14 20", width=2),
    "draft": p("M7 4 L17 4 L20 20 L4 20 Z") + acc("M17 4 L17 20 M17 13 A4 4 0 0 0 18.6 12.6", width=1.2),
    "parameters": p("M4 6 L20 6 M4 12 L20 12 M4 18 L20 18") + acc("M8 4 L8 8 M15 10 L15 14 M10 16 L10 20", width=2.4),
    "link_params": p("M10 14 L14 10") + acc("M8.5 11.5 L6 14 A3.5 3.5 0 0 0 11 19 L13.5 16.5 M15.5 12.5 L18 10 A3.5 3.5 0 0 0 13 5 L10.5 7.5"),
    "history": circle(12, 12, 8.5) + acc("M12 7 L12 12 L15.5 14") + p("M2 5 L3.5 9 L7.5 7.5", width=1.4),
    "component_new": small_cube(0, 0, 0.75) + acc("M18 14 L18 22 M14 18 L22 18"),
    "component_select": small_cube(0, 0, 0.75) + acc("M13 12 L13 22 L15.5 19.5 L18 23 L19.5 22 L17 18.5 L20.5 18 Z", fill=A),
    "component_out": small_cube(0, 0, 0.75) + acc("M13 17 L22 17 M19 14 L22 17 L19 20"),
    "components": small_cube(0, 0, 0.5) + small_cube(10, 0, 0.5) + g("translate(5 10) scale(0.5)", acc(CUBE, width=3.2)),
    "plane_distance": p("M3 20 L8 15 L21 15 L16 20 Z") + acc("M3 9 L8 4 L21 4 L16 9 Z") + p("M12 9.5 L12 14.5", width=1.2),
    "plane_angle": p("M2 19 L22 19") + acc("M2 19 L18 5") + p("M8 19 A6 6 0 0 0 6.5 15", width=1.2),
    "plane_mid": p("M3 6 L21 6 M3 20 L21 20") + dashed("M3 13 L21 13"),
    "plane_3pt": plane_icon(dot(7, 13.5) + dot(12, 10.5) + dot(16.5, 13)),
    "plane_tangent": circle(12, 9, 6) + acc("M2 17 L7 15 L22 15 L17 17 Z", fill=A, width=1.2, extra=' fill-opacity="0.35"'),
    "plane_path": p("M3 20 C10 20 14 12 14 3", width=1.2) + acc("M8 18 L13 12 L19 12 L14 18 Z"),
    "axis_round": p("M7 7 A5 2 0 1 0 17 7 A5 2 0 1 0 7 7 M7 7 L7 17 A5 2 0 0 0 17 17 L17 7") + acc("M12 2 L12 22", width=1.4,
                                                                                             extra=' stroke-dasharray="3 1.5"'),
    "axis_2pt": acc("M3 21 L21 3") + dot(7, 17, 2.4, I) + dot(17, 7, 2.4, I),
    "axis_face": p(PLANE) + acc("M12 12 L12 2"),
    "axis_edge": p(CUBE) + acc("M20 7.5 L20 16.5", width=3),
    "axis_planes": p("M2 18 L10 10 L10 3 L2 11 Z M22 18 L10 10 L10 3 L22 11 Z", width=1.2) + acc("M10 2 L10 21", width=2),
    "point_click": p("M5 3 L5 17 L8.5 13.5 L11 19 L13 18 L10.5 12.5 L15 12.5 Z") + dot(18, 18, 3),
    "point_face": p("M3 18 L8 8 L21 8 L16 18 Z") + dot(12, 13, 2.6),
    "point_edge": p("M4 20 L18 6") + dot(18, 6, 3),
    "point_planes": p("M2 8 L22 8 M12 2 L12 22 M4 20 L20 4", width=1.2) + dot(12, 12, 3),
    "point_axis": p(PLANE) + acc("M12 2 L12 22", width=1.2) + dot(12, 12, 2.8, I),
    "section": p("M4 7.5 L12 3 L20 7.5 L20 16.5 L12 21 L4 16.5 Z M12 12 L12 21 M4 7.5 L12 12") + acc("M12 3 L12 12 L20 7.5 Z M12 12 L20 7.5 L20 16.5 L12 21 Z",
                                                                                                  fill=A, width=1.2, extra=' fill-opacity="0.45"'),
    "measure_faces": p("M4 3 L4 21 M20 3 L20 21") + acc("M6 12 L18 12 M8.5 9.5 L6 12 L8.5 14.5 M15.5 9.5 L18 12 L15.5 14.5"),
    "radius": circle(12, 12, 9) + acc("M12 12 L18.4 5.6") + dot(12, 12, 1.6, I),
    "edge_length": p("M3 16 L21 16", width=2.4) + acc("M3 9 L21 9 M5.5 6.5 L3 9 L5.5 11.5 M18.5 6.5 L21 9 L18.5 11.5 M3 6 L3 12 M21 6 L21 12", width=1.2),
    "volume": acc(CUBE_TOP, fill=A, width=0.01, extra=' fill-opacity="0.25"') + acc(CUBE_FRONT, fill=A, width=0.01,
                                                                                  extra=' fill-opacity="0.45"') + p(CUBE),
    "part_distance": p("M2 6 L8 6 L8 18 L2 18 Z") + circle(18.5, 12, 3.5) + acc("M9.5 12 L14 12 M11.5 10 L9.5 12 L11.5 14", width=1.3),
    "view_home": p("M3 11 L12 3 L21 11 M5.5 9 L5.5 21 L18.5 21 L18.5 9") + acc("M10 21 L10 15 L14 15 L14 21"),
    "view_front": view(CUBE_FRONT),
    "view_right": view(CUBE_RIGHT),
    "view_top": view(CUBE_TOP),
    "zoom_selection": circle(10, 10, 6.5) + p("M15 15 L21 21", width=2.4) + acc("M10 7 L10 13 M7 10 L13 10"),
    "search": circle(10, 10, 6.5) + acc("M15 15 L21 21", width=2.4),
    "theme": p("M12 3 A9 9 0 1 0 12 21 C14 21 14 18.5 13 17.5 C12 16.5 12.5 14.5 14.5 14.5 L17 14.5 A4 4 0 0 0 21 10.5 C21 6.5 17 3 12 3 Z")
    + dot(7.5, 11, 1.6) + dot(10, 7, 1.6) + dot(15, 7.5, 1.6),
    "theme_editor": p("M12 3 A9 9 0 1 0 12 21 C14 21 14 18.5 13 17.5 C12 16.5 12.5 14.5 14.5 14.5 L17 14.5 A4 4 0 0 0 21 10.5 C21 6.5 17 3 12 3 Z")
    + acc("M14 22 L22 14 L20 12 L12 20 Z", fill=A),
    "welcome": circle(12, 12, 9) + acc("M12 11 L12 17") + dot(12, 7.5, 1.4),
    "panel": p("M3 4 L21 4 L21 20 L3 20 Z") + acc("M15 4 L15 20 M17 8 L19 8 M17 11 L19 11"),
    "palette_select": p("M6 3 L6 19 L10 15 L13 21 L15.5 20 L12.5 14 L18 14 Z"),
    "hardware": circle(12, 6, 4) + p("M10 10 L10 21 L14 21 L14 10") + acc("M10 13 L14 14.5 M10 16 L14 17.5"),
    "screw_plain": p("M2 4 L22 4 L22 20 L2 20 Z", width=1.2) + acc("M9 4 L9 20 M15 4 L15 20"),
    "screw_countersunk": p("M2 4 L22 4 L22 20 L2 20 Z", width=1.2) + acc("M5 4 L9.5 9 L9.5 20 M19 4 L14.5 9 L14.5 20"),
    "screw_counterbored": p("M2 4 L22 4 L22 20 L2 20 Z", width=1.2) + acc("M6 4 L6 9 L9.5 9 L9.5 20 M18 4 L18 9 L14.5 9 L14.5 20"),
    "nut_trap": p("M12 3 L19.8 7.5 L19.8 16.5 L12 21 L4.2 16.5 L4.2 7.5 Z") + circle(12, 12, 4, A),
    "insert": p("M7 4 L17 4 L17 20 L7 20 Z") + acc("M7 7 L17 9 M7 10 L17 12 M7 13 L17 15 M7 16 L17 18") + circle(12, 4, 2, I),
    "magnet": p("M5 4 L5 13 A7 7 0 0 0 19 13 L19 4 L15 4 L15 13 A3 3 0 0 1 9 13 L9 4 Z") + acc("M5 4 L9 4 L9 7 L5 7 Z M15 4 L19 4 L19 7 L15 7 Z", fill=A),
}

for _axis in "xyz":
    for _mode in ("min", "center", "max"):
        ICONS[f"align_{_mode}_{_axis}"] = align(_mode, _axis)


def write_icons() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    missing = ui_catalog.icon_names() - set(ICONS)
    if missing:
        raise SystemExit(f"no drawing for icons: {sorted(missing)}")
    for name, body in sorted(ICONS.items()):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
               f"{body}</svg>\n")
        (ICON_DIR / f"{name}.svg").write_text(svg)
    return len(ICONS)


# --- thumbnails ----------------------------------------------------------------

# The 3D view's home camera looks from (1, -1, 0.8) towards the origin.
VIEW = np.array([1.0, -1.0, 0.8])
LIGHT = np.array([0.35, -0.6, 1.0])
SIZE = 128
HOLE_COLOR = "#e8a33d"


def _camera():
    forward = -VIEW / np.linalg.norm(VIEW)
    right = np.cross(forward, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return forward, right, up


def _shade(color: str, amount: float) -> str:
    rgb = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    shaded = np.clip(rgb * (0.35 + 0.75 * amount), 0, 255)
    return "#" + "".join(f"{int(round(v)):02x}" for v in shaded)


def thumbnail_svg(meshes) -> str:
    """`meshes`: (trimesh, colour) pairs, drawn together."""
    forward, right, up = _camera()
    light = LIGHT / np.linalg.norm(LIGHT)
    polygons = []
    all_points = []
    for tm, color in meshes:
        points = np.column_stack([tm.vertices @ right, tm.vertices @ up])
        depth = tm.vertices @ forward
        all_points.append(points)
        for face, normal in zip(tm.faces, tm.face_normals):
            if normal @ forward >= 0:  # facing away
                continue
            amount = max(0.0, float(normal @ light)) * 0.8 + 0.2
            polygons.append((depth[face].mean(), points[face], _shade(color, amount)))
    stacked = np.vstack(all_points)
    low, high = stacked.min(axis=0), stacked.max(axis=0)
    scale = (SIZE - 12) / max(high - low)
    centre = (low + high) / 2
    polygons.sort(key=lambda item: -item[0])
    out = []
    for _depth, points, color in polygons:
        xy = (points - centre) * scale
        coords = " ".join(f"{SIZE / 2 + x:.1f},{SIZE / 2 - y:.1f}" for x, y in xy)
        out.append(f'<polygon points="{coords}" fill="{color}" stroke="{color}" stroke-width="0.6" '
                   f'stroke-linejoin="round"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
            f'viewBox="0 0 {SIZE} {SIZE}">' + "".join(out) + "</svg>\n")


def _shape_meshes(item_key: str):
    kind, _, name = item_key.partition(":")
    if kind == "shape":
        return [(shape_geometry(new_primitive(name)), DEFAULT_COLOR)]
    if kind == "hardware":
        for key, _label, primitive, params in ui_catalog.hardware_inserts():
            if key == item_key:
                shape = new_primitive(primitive)
                shape.params.update(params)
                return [(shape_geometry(shape), HOLE_COLOR)]
    if item_key == "command:shape.add_text":
        shape = new_primitive("text")
        shape.params.update(text="Aa", letter_height=10.0, depth=3.0)
        return [(shape_geometry(shape), DEFAULT_COLOR)]
    if item_key == "command:shape.box_with_lid":
        values = {key: default for key, _label, default, _options in panels.box_with_lid_fields()}
        parts = builders.box_with_lid(**values, clearances={"press": 0.1, "snug": 0.2, "loose": 0.4})
        return [(shape_geometry(part), DEFAULT_COLOR) for part in parts]
    raise KeyError(item_key)


def write_thumbnails() -> int:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in ui_catalog.insert_items():
        meshes = _shape_meshes(item["key"])
        (THUMBNAIL_DIR / f"{item['thumbnail']}.svg").write_text(thumbnail_svg(meshes))
        count += 1
    return count


if __name__ == "__main__":
    assert all(kind in PRIMITIVES for kind in ("cube", "text"))
    print(f"{write_icons()} icons, {write_thumbnails()} thumbnails")
