"""Ready-made holes for real hardware: screws, nuts, heat-set inserts, magnets.

Every dimension lives in TABLE below, with the standard or datasheet it came
from. A value marked `# verify` is one we are not certain of (heat-set
inserts in particular vary by brand); check it against the parts you
actually have before relying on it.

Every hole is built with its opening at the top (Z = its full depth) and its
body going down to Z = 0, so it can be sunk into the top face of a part --
which is exactly how "Place on face" puts a Hole into a surface. A fit
clearance, when given, is added on every side and at both ends.
"""

import numpy as np
import trimesh

from mesh.solids import from_manifold, m3

SCREW_SIZES = ("M2", "M2.5", "M3", "M4", "M5", "M6")
INSERT_SIZES = ("M2", "M2.5", "M3", "M4", "M5")

# fmt: off
# One row per (part, size). All values in millimetres.
TABLE: dict[tuple[str, str], dict[str, float]] = {
    # --- Screw clearance holes: ISO 273, "medium" series (hole diameter). ---
    ("clearance", "M2"):   {"diameter": 2.4},   # ISO 273 medium
    ("clearance", "M2.5"): {"diameter": 2.9},   # ISO 273 medium
    ("clearance", "M3"):   {"diameter": 3.4},   # ISO 273 medium
    ("clearance", "M4"):   {"diameter": 4.5},   # ISO 273 medium
    ("clearance", "M5"):   {"diameter": 5.5},   # ISO 273 medium
    ("clearance", "M6"):   {"diameter": 6.6},   # ISO 273 medium

    # --- Countersinks, 90 degrees, for flat (countersunk) head screws. ---
    # Top diameter = the theoretical maximum head diameter of ISO 7046 / ISO 2009
    # flat head screws, which is also the countersink diameter ISO 15065 gives.
    ("countersink", "M2"):   {"diameter": 4.4},    # ISO 7046-1 dk theoretical max
    ("countersink", "M2.5"): {"diameter": 5.5},    # ISO 7046-1 dk theoretical max
    ("countersink", "M3"):   {"diameter": 6.3},    # ISO 7046-1 dk theoretical max
    ("countersink", "M4"):   {"diameter": 9.4},    # ISO 7046-1 dk theoretical max
    ("countersink", "M5"):   {"diameter": 10.4},   # ISO 7046-1 dk theoretical max
    ("countersink", "M6"):   {"diameter": 12.6},   # ISO 7046-1 dk theoretical max

    # --- Counterbores for socket head cap screws (ISO 4762). ---
    # Diameter: DIN 974-1 counterbore for ISO 4762 heads. Depth: ISO 4762 head
    # height k (max), so the head sits flush with the surface.
    ("counterbore", "M2"):   {"diameter": 4.4,  "depth": 2.0},   # DIN 974-1 # verify; k max ISO 4762
    ("counterbore", "M2.5"): {"diameter": 5.5,  "depth": 2.5},   # DIN 974-1 # verify; k max ISO 4762
    ("counterbore", "M3"):   {"diameter": 6.5,  "depth": 3.0},   # DIN 974-1 # verify; k max ISO 4762
    ("counterbore", "M4"):   {"diameter": 8.0,  "depth": 4.0},   # DIN 974-1 # verify; k max ISO 4762
    ("counterbore", "M5"):   {"diameter": 10.0, "depth": 5.0},   # DIN 974-1 # verify; k max ISO 4762
    ("counterbore", "M6"):   {"diameter": 11.0, "depth": 6.0},   # DIN 974-1 # verify; k max ISO 4762

    # --- Hex nuts: ISO 4032. "flats" = width across flats s, "depth" = nut
    # height m (max). ---
    ("nut", "M2"):   {"flats": 4.0,  "depth": 1.6},   # ISO 4032
    ("nut", "M2.5"): {"flats": 5.0,  "depth": 2.0},   # ISO 4032
    ("nut", "M3"):   {"flats": 5.5,  "depth": 2.4},   # ISO 4032
    ("nut", "M4"):   {"flats": 7.0,  "depth": 3.2},   # ISO 4032
    ("nut", "M5"):   {"flats": 8.0,  "depth": 4.7},   # ISO 4032
    ("nut", "M6"):   {"flats": 10.0, "depth": 5.2},   # ISO 4032

    # --- Heat-set insert pockets: recommended hole diameter and depth for
    # common tapered brass inserts (e.g. CNC Kitchen / ruthex style). These
    # vary by brand -- use your insert's datasheet. ---
    ("insert", "M2"):   {"diameter": 3.2, "depth": 4.0},    # verify
    ("insert", "M2.5"): {"diameter": 3.6, "depth": 4.5},    # verify
    ("insert", "M3"):   {"diameter": 4.0, "depth": 6.0},    # verify
    ("insert", "M4"):   {"diameter": 5.6, "depth": 8.0},    # verify
    ("insert", "M5"):   {"diameter": 6.4, "depth": 10.0},   # verify

    # --- Magnet pockets: the magnet's own diameter x height. Common disc
    # magnet sizes; the fit clearance supplies the room around them. ---
    ("magnet", "10x2"): {"diameter": 10.0, "depth": 2.0},   # nominal magnet size
    ("magnet", "8x2"):  {"diameter": 8.0,  "depth": 2.0},   # nominal magnet size
    ("magnet", "6x2"):  {"diameter": 6.0,  "depth": 2.0},   # nominal magnet size
    ("magnet", "4x2"):  {"diameter": 4.0,  "depth": 2.0},   # nominal magnet size
}
# fmt: on

MAGNET_PRESETS = ("10x2", "8x2", "6x2", "4x2")

HEAD_CHOICES = [("plain", "Plain"), ("countersunk", "Countersunk"), ("counterbored", "Counterbored")]

# The fit each kind of hole starts with. Screw clearance holes are already
# a clearance size (ISO 273), and heat-set inserts are melted into a hole
# that is meant to be undersized, so both start Exact. A nut trap needs a
# little room to drop the nut in; a magnet should be held tight.
DEFAULT_FIT = {
    "screw_hole": "exact",
    "nut_trap": "snug",
    "insert_pocket": "exact",
    "magnet_pocket": "press",
}

SEGMENTS = 64


def dim(part: str, size: str, name: str) -> float:
    return float(TABLE[(part, size)][name])


def _cylinder(radius: float, z0: float, z1: float, segments: int = SEGMENTS) -> "m3.Manifold":
    return m3.Manifold.cylinder(z1 - z0, radius, radius, segments).translate((0.0, 0.0, z0))


def _cone(r_bottom: float, r_top: float, z0: float, z1: float) -> "m3.Manifold":
    return m3.Manifold.cylinder(z1 - z0, r_bottom, r_top, SEGMENTS).translate((0.0, 0.0, z0))


def _hexagon(flats: float, z0: float, z1: float) -> "m3.Manifold":
    circumradius = (flats / 2.0) / np.cos(np.pi / 6.0)
    return _cylinder(circumradius, z0, z1, segments=6)


def screw_hole(size: str, head: str, depth: float, clearance: float = 0.0) -> trimesh.Trimesh:
    c = clearance
    bore = dim("clearance", size, "diameter") / 2.0 + c
    solid = _cylinder(bore, -c, depth + c)
    if head == "countersunk":
        top = dim("countersink", size, "diameter") / 2.0 + c
        # 90 degree countersink: the radius shrinks 1 mm per 1 mm of depth.
        drop = min(top - bore, depth)
        solid = solid + _cone(top - drop, top + c, depth - drop, depth + c)
    elif head == "counterbored":
        radius = dim("counterbore", size, "diameter") / 2.0 + c
        recess = min(dim("counterbore", size, "depth"), depth)
        solid = solid + _cylinder(radius, depth - recess - c, depth + c)
    elif head != "plain":
        raise ValueError(f"unknown screw head {head!r}")
    return from_manifold(solid)


def nut_trap(size: str, depth: float, clearance: float = 0.0) -> trimesh.Trimesh:
    """A hex pocket at the top for the nut, with the screw's clearance hole
    below it."""
    c = clearance
    nut_depth = min(dim("nut", size, "depth"), depth)
    bore = dim("clearance", size, "diameter") / 2.0 + c
    solid = _cylinder(bore, -c, depth + c)
    solid = solid + _hexagon(dim("nut", size, "flats") + 2.0 * c, depth - nut_depth - c, depth + c)
    return from_manifold(solid)


def insert_pocket(size: str, clearance: float = 0.0) -> trimesh.Trimesh:
    c = clearance
    radius = dim("insert", size, "diameter") / 2.0 + c
    return from_manifold(_cylinder(radius, -c, dim("insert", size, "depth") + c))


def magnet_pocket(diameter: float, depth: float, clearance: float = 0.0) -> trimesh.Trimesh:
    c = clearance
    return from_manifold(_cylinder(diameter / 2.0 + c, -c, depth + c))


def build(kind: str, p: dict, clearance: float = 0.0) -> trimesh.Trimesh:
    """Geometry for one of the hardware primitives in mesh.shapes.PRIMITIVES."""
    if kind == "screw_hole":
        return screw_hole(p["size"], p["head"], float(p["depth"]), clearance)
    if kind == "nut_trap":
        return nut_trap(p["size"], float(p["depth"]), clearance)
    if kind == "insert_pocket":
        return insert_pocket(p["size"], clearance)
    if kind == "magnet_pocket":
        return magnet_pocket(float(p["diameter"]), float(p["depth"]), clearance)
    raise KeyError(f"unknown hardware hole: {kind}")


def menu_presets() -> list[tuple[str, list[tuple[str, str, dict]]]]:
    """The "Add hardware hole" menu: (submenu label, [(item label, primitive,
    params), ...]). Pure data, so the menu and its tests share one source."""
    screws = [
        (f"Screw hole ({label.lower()})", [
            (size, "screw_hole", {"size": size, "head": head}) for size in SCREW_SIZES
        ])
        for head, label in HEAD_CHOICES
    ]
    return screws + [
        ("Nut trap", [(size, "nut_trap", {"size": size}) for size in SCREW_SIZES]),
        ("Heat-set insert pocket", [
            (size, "insert_pocket", {"size": size}) for size in INSERT_SIZES
        ]),
        ("Magnet pocket", [
            (f"{key.replace('x', ' × ')} mm", "magnet_pocket", {
                "diameter": dim("magnet", key, "diameter"),
                "depth": dim("magnet", key, "depth"),
            })
            for key in MAGNET_PRESETS
        ]),
    ]


def preset_name(primitive: str, params: dict) -> str:
    if primitive == "screw_hole":
        head = dict(HEAD_CHOICES)[params["head"]].lower()
        return f"{params['size']} screw hole ({head})"
    if primitive == "nut_trap":
        return f"{params['size']} nut trap"
    if primitive == "insert_pocket":
        return f"{params['size']} insert pocket"
    if primitive == "magnet_pocket":
        return f"Magnet pocket {params['diameter']:g} × {params['depth']:g} mm"
    raise KeyError(primitive)
