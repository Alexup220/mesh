"""Reading and writing files: model imports, exports, and .mesh projects."""

import json
import logging
import uuid
from pathlib import Path

import numpy as np
import trimesh

from mesh.blobs import encode_mesh
from mesh.scene import DEFAULT_COLOR, Scene, Shape

logger = logging.getLogger(__name__)

IMPORT_EXTS = (".stl", ".obj", ".3mf", ".ply", ".glb", ".gltf", ".off", ".dae")
PROJECT_EXT = ".mesh"
PROJECT_FORMAT_VERSION = 1

MAX_BODIES = 200


class MeshImportError(Exception):
    """A model file could not be read."""


def suggest_unit_scale(tm: trimesh.Trimesh) -> tuple[float, str] | None:
    """Guess whether a file is in metres rather than millimetres.

    Only the metres case is confident enough to act on: a printable part
    under 1 mm across is almost never what someone meant.
    """
    longest = float((tm.bounds[1] - tm.bounds[0]).max())
    if 0.0 < longest < 1.0:
        return 1000.0, "metres"
    return None


def _as_meshes(loaded) -> list[trimesh.Trimesh]:
    if isinstance(loaded, trimesh.Scene):
        return [g for g in loaded.dump() if isinstance(g, trimesh.Trimesh)]
    if isinstance(loaded, trimesh.Trimesh):
        return [loaded]
    return []


def import_meshes(path) -> list[Shape]:
    path = Path(path)
    if path.suffix.lower() not in IMPORT_EXTS:
        raise MeshImportError(
            f"mesh cannot open {path.suffix} files. Try {', '.join(IMPORT_EXTS)}."
        )
    if not path.exists():
        raise MeshImportError(f"{path.name} does not exist.")

    try:
        loaded = trimesh.load(path, force=None)
    except Exception as exc:
        logger.warning("failed to load %s: %s", path, exc)
        raise MeshImportError(
            f"{path.name} could not be opened. It may be damaged or saved in "
            "an unsupported variant of that file type."
        ) from exc

    meshes = _as_meshes(loaded)
    if not meshes:
        raise MeshImportError(f"{path.name} contains no 3D shapes.")

    bodies: list[trimesh.Trimesh] = []
    for tm in meshes:
        parts = tm.split(only_watertight=False)
        bodies.extend(parts if 0 < len(parts) <= MAX_BODIES else [tm])

    shapes = []
    for index, body in enumerate(bodies):
        name = path.stem if len(bodies) == 1 else f"{path.stem} {index + 1}"
        shapes.append(
            Shape(
                id=uuid.uuid4().hex,
                name=name,
                kind="imported",
                params={"blob": encode_mesh(body), "source": path.name},
                transform=np.eye(4, dtype=np.float64),
                color=DEFAULT_COLOR,
            )
        )
    return shapes
