"""How construction guides look (Expert mode's Construct menu).

A construction guide is shown and saved but never printed, like a sketch
(see mesh.shapes.is_reference). Each is drawn in its own coordinates and
placed by its transform:

    plane  a square `size` mm across in its X and Y, with a short tick
           along its Z showing the way it faces

The shading is what a click on the guide hits, and what the rest of the
app measures (its size and middle). A plane goes on without end; only the
square is drawn.
"""

import numpy as np
import trimesh

KINDS = ("plane",)

PLANE_SIZE = 60.0  # mm across, unless made to fit a face


def guide_lines(kind: str, params: dict) -> list[np.ndarray]:
    """The guide's lines, as (N, 3) polylines in its own coordinates."""
    if kind == "plane":
        h = float(params.get("size", PLANE_SIZE)) / 2.0
        square = np.array([[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0], [-h, -h, 0]], dtype=np.float64)
        tick = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, h * 0.3]])
        return [square, tick]
    raise KeyError(f"unknown guide: {kind}")


def guide_geometry(kind: str, params: dict) -> trimesh.Trimesh:
    """The guide's shading, in its own coordinates."""
    if kind == "plane":
        h = float(params.get("size", PLANE_SIZE)) / 2.0
        vertices = np.array([[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]], dtype=np.float64)
        return trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    raise KeyError(f"unknown guide: {kind}")
