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


EXPORT_EXTS = (".stl", ".3mf", ".obj")


class ExportError(Exception):
    """A model could not be written."""


def export_scene(scene: Scene, path) -> None:
    """Write the combined model, refusing to emit a broken mesh.

    A beginner cannot tell a bad STL from a good one until a print fails
    hours in, so a hard refusal here is worth more than a warning.
    """
    from mesh.ops import NothingToCombineError, evaluate

    path = Path(path)
    if path.suffix.lower() not in EXPORT_EXTS:
        raise ExportError(
            f"mesh cannot save {path.suffix} files. Try {', '.join(EXPORT_EXTS)}."
        )

    visible = [s for s in scene.shapes if s.visible]
    try:
        result = evaluate(visible)
    except NothingToCombineError as exc:
        raise ExportError("There is nothing to save yet — add a shape first.") from exc

    if not result.is_watertight:
        result = result.copy()
        result.fill_holes()
        result.update_faces(result.nondegenerate_faces())
        result.merge_vertices()

    if not result.is_watertight:
        raise ExportError(
            "This model has gaps in it and would not print correctly. "
            "Try grouping your shapes so they join into one solid piece."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    result.export(path)


def save_project(scene: Scene, path) -> None:
    path = Path(path)
    document = {"format_version": PROJECT_FORMAT_VERSION, "scene": scene.to_dict()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


def load_project(path) -> Scene:
    path = Path(path)
    try:
        document = json.loads(path.read_text())
        return Scene.from_dict(document["scene"])
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
        logger.warning("failed to load project %s: %s", path, exc)
        raise ExportError(f"{path.name} is not a mesh project file.") from exc
