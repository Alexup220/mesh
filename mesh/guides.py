"""How construction guides look (Expert mode's Construct menu).

A construction guide is shown and saved but never printed, like a sketch
(see mesh.shapes.is_reference). Each is drawn in its own coordinates and
placed by its transform:

    plane  a square `size` mm across in its X and Y, with a short tick
           along its Z showing the way it faces
    axis   a line `length` mm long along its Z, centred on its origin,
           with an arrowhead at the end it points to

The shading is what a click on the guide hits, and what the rest of the
app measures (its size and middle). Planes and axes go on without end;
only the square and the line are drawn.
"""

import numpy as np
import trimesh

KINDS = ("plane", "axis")

PLANE_SIZE = 60.0  # mm across, unless made to fit a face
AXIS_LENGTH = 120.0
AXIS_THICKNESS = 1.2  # the shading round an axis, so a click can land on it


def guide_lines(kind: str, params: dict) -> list[np.ndarray]:
    """The guide's lines, as (N, 3) polylines in its own coordinates."""
    if kind == "plane":
        h = float(params.get("size", PLANE_SIZE)) / 2.0
        square = np.array([[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0], [-h, -h, 0]], dtype=np.float64)
        tick = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, h * 0.3]])
        return [square, tick]
    if kind == "axis":
        h = float(params.get("length", AXIS_LENGTH)) / 2.0
        head = min(4.0, h / 4.0)
        line = np.array([[0.0, 0.0, -h], [0.0, 0.0, h]])
        arrow = np.array([[-head / 2, 0.0, h - head], [0.0, 0.0, h], [head / 2, 0.0, h - head]])
        return [line, arrow]
    raise KeyError(f"unknown guide: {kind}")


def guide_geometry(kind: str, params: dict) -> trimesh.Trimesh:
    """The guide's shading, in its own coordinates."""
    if kind == "plane":
        h = float(params.get("size", PLANE_SIZE)) / 2.0
        vertices = np.array([[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]], dtype=np.float64)
        return trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    if kind == "axis":
        length = float(params.get("length", AXIS_LENGTH))
        return trimesh.creation.cylinder(radius=AXIS_THICKNESS / 2.0, height=length, sections=6)
    raise KeyError(f"unknown guide: {kind}")
