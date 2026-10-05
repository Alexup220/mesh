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
# A project that uses Expert mode's named parameters, links, components or
# history is saved as version 2: older builds of mesh would open it but
# silently drop those. A project that uses none is still saved as 1.
EXPERT_FORMAT_VERSION = 2
EXPERT_KEYS = ("parameters", "components", "history")

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


class ProjectError(Exception):
    """A .mesh project or export could not be read or written.

    Covers both directions -- export failures and project load
    failures -- because both boil down to the same user-facing fact:
    "this file could not be turned into/from a scene."
    """


# Kept as an alias: this was named ExportError before it also became the
# exception load_project() raises, and several call sites (and tests)
# still refer to it by that name.
ExportError = ProjectError


def export_scene(scene: Scene, path) -> None:
    """Write the combined model, refusing to emit a broken mesh.

    A beginner cannot tell a bad STL from a good one until a print fails
    hours in, so a hard refusal here is worth more than a warning.
    """
    from mesh.ops import HasGapsError, NothingLeftError, NothingToCombineError, evaluate

    path = Path(path)
    if path.suffix.lower() not in EXPORT_EXTS:
        raise ProjectError(
            f"mesh cannot save {path.suffix} files. Try {', '.join(EXPORT_EXTS)}."
        )

    visible = [s for s in scene.shapes if s.visible]
    try:
        result = evaluate(visible, clearances=scene.fit_clearances)
    except HasGapsError as exc:
        raise ProjectError(str(exc)) from exc
    except NothingLeftError as exc:
        raise ProjectError(
            "There is nothing to save: the holes cut away all of the solid parts. "
            "Move a hole or make it smaller."
        ) from exc
    except NothingToCombineError as exc:
        raise ProjectError("There is nothing to save yet — add a shape first.") from exc

    if not result.is_watertight:
        result = result.copy()
        result.fill_holes()
        result.update_faces(result.nondegenerate_faces())
        result.merge_vertices()

    if not result.is_watertight:
        raise ProjectError(
            "This model has gaps in it and would not print correctly. "
            "Try grouping your shapes so they join into one solid piece."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    result.export(path)


def format_version(scene_dict: dict) -> int:
    """The project file version a scene needs (see EXPERT_FORMAT_VERSION)."""
    expert = any(key in scene_dict for key in EXPERT_KEYS) or any(
        "links" in s or "component" in s for s in scene_dict.get("shapes", []))
    return EXPERT_FORMAT_VERSION if expert else PROJECT_FORMAT_VERSION


def save_project(scene: Scene, path) -> None:
    path = Path(path)
    data = scene.to_dict()
    document = {"format_version": format_version(data), "scene": data}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


def load_project(path) -> Scene:
    path = Path(path)
    try:
        document = json.loads(path.read_text())
        version = document.get("format_version", PROJECT_FORMAT_VERSION)
        if isinstance(version, (int, float)) and version > EXPERT_FORMAT_VERSION:
            raise ProjectError(f"{path.name} was saved by a newer version of mesh. Update mesh to open it.")
        return Scene.from_dict(document["scene"])
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,  # a file whose top level is not an object
        OSError,
        ValueError,  # e.g. np.array() on a malformed "transform" entry
    ) as exc:
        logger.warning("failed to load project %s: %s", path, exc)
        raise ProjectError(f"{path.name} is not a mesh project file.") from exc
