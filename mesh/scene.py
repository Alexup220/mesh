"""Document model: shapes, selection, and undo history.

A Shape stores parameters and a transform. Triangle geometry is derived
from those by mesh.shapes, never stored here — which is what makes undo,
save/load, and the numeric inspector correct by construction.
"""

import copy
import uuid
from dataclasses import dataclass, field

import numpy as np

from mesh.shapes import PRIMITIVES, default_params

HISTORY_LIMIT = 50
DEFAULT_BUILD_VOLUME = (220.0, 220.0, 250.0)
DEFAULT_SNAP_MM = 1.0
DEFAULT_COLOR = "#4a90d9"


@dataclass
class Shape:
    id: str
    name: str
    kind: str
    params: dict
    transform: np.ndarray
    color: str = DEFAULT_COLOR
    is_hole: bool = False
    visible: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "params": self.params,
            "transform": np.asarray(self.transform, dtype=np.float64).tolist(),
            "color": self.color,
            "is_hole": self.is_hole,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Shape":
        return cls(
            id=d["id"],
            name=d["name"],
            kind=d["kind"],
            params=d["params"],
            transform=np.array(d["transform"], dtype=np.float64),
            color=d.get("color", DEFAULT_COLOR),
            is_hole=d.get("is_hole", False),
            visible=d.get("visible", True),
        )


def new_primitive(primitive: str, name: str | None = None) -> Shape:
    params = default_params(primitive)
    params["primitive"] = primitive
    return Shape(
        id=uuid.uuid4().hex,
        name=name or PRIMITIVES[primitive]["label"],
        kind="primitive",
        params=params,
        transform=np.eye(4, dtype=np.float64),
    )


@dataclass
class Scene:
    shapes: list[Shape] = field(default_factory=list)
    selection: list[str] = field(default_factory=list)
    build_volume: tuple[float, float, float] = DEFAULT_BUILD_VOLUME
    snap_mm: float = DEFAULT_SNAP_MM

    def add(self, shape: Shape) -> None:
        self.shapes.append(shape)

    def remove(self, ids) -> None:
        drop = set(ids)
        self.shapes = [s for s in self.shapes if s.id not in drop]
        self.selection = [i for i in self.selection if i not in drop]

    def get(self, shape_id: str) -> Shape:
        for s in self.shapes:
            if s.id == shape_id:
                return s
        raise KeyError(shape_id)

    def select(self, ids) -> None:
        known = {s.id for s in self.shapes}
        self.selection = [i for i in ids if i in known]

    def selected(self) -> list[Shape]:
        chosen = set(self.selection)
        return [s for s in self.shapes if s.id in chosen]

    def to_dict(self) -> dict:
        return {
            "shapes": [s.to_dict() for s in self.shapes],
            "selection": list(self.selection),
            "build_volume": list(self.build_volume),
            "snap_mm": self.snap_mm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(
            shapes=[Shape.from_dict(s) for s in d.get("shapes", [])],
            selection=list(d.get("selection", [])),
            build_volume=tuple(d.get("build_volume", DEFAULT_BUILD_VOLUME)),
            snap_mm=d.get("snap_mm", DEFAULT_SNAP_MM),
        )


class Document:
    """A scene plus its undo history.

    Call snapshot() BEFORE mutating the scene. Snapshots are whole-scene
    deep copies; scenes hold at most a few hundred shapes, so this costs
    microseconds and removes an entire class of undo bugs.
    """

    def __init__(self, scene: Scene | None = None) -> None:
        self.scene = scene or Scene()
        self._undo: list[Scene] = []
        self._redo: list[Scene] = []

    def snapshot(self, label: str = "") -> None:
        self._undo.append(copy.deepcopy(self.scene))
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.scene))
        self.scene = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.scene))
        self.scene = self._redo.pop()
        return True
