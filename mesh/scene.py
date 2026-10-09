"""Document model: shapes, selection, and undo history.

A Shape stores parameters and a transform. Triangle geometry is derived
from those by mesh.shapes, never stored here — which is what makes undo,
save/load, and the numeric inspector correct by construction.
"""

import copy
import math
import uuid
from dataclasses import dataclass, field

import numpy as np

from mesh.shapes import PRIMITIVES, default_params

HISTORY_LIMIT = 50
DEFAULT_BUILD_VOLUME = (220.0, 220.0, 250.0)
DEFAULT_SNAP_MM = 1.0
DEFAULT_COLOR = "#4a90d9"

# How snugly a Hole fits whatever goes into it. The clearance (mm) is added
# on every side of the hole when its geometry is evaluated, so a 10 mm hole
# with a 0.2 mm "snug" clearance comes out 10.4 mm across. "exact" adds
# nothing and is what every shape -- and every project saved before fits
# existed -- starts as.
FITS = {
    "exact": "Exact",
    "press": "Press fit",
    "snug": "Snug fit",
    "loose": "Loose fit",
}
DEFAULT_FIT = "exact"
DEFAULT_FIT_CLEARANCES = {"press": 0.1, "snug": 0.2, "loose": 0.4}
MAX_FIT_CLEARANCE = 2.0  # mm per side; the Fit clearances dialog allows no more


def _read_fit_clearances(raw) -> dict:
    """The fit clearances from a project file. Anything missing, damaged or
    out of range falls back to the default for that fit, so a hand-edited
    file still opens and never gives a hole a negative or endless size."""
    clearances = dict(DEFAULT_FIT_CLEARANCES)
    if not isinstance(raw, dict):
        return clearances
    for key in DEFAULT_FIT_CLEARANCES:
        try:
            value = float(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and 0.0 <= value <= MAX_FIT_CLEARANCE:
            clearances[key] = value
    return clearances


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
    fit: str = DEFAULT_FIT
    # Expert mode: numbers that follow a named parameter's formula (field
    # -> formula; see mesh.parameters), and the component the part belongs
    # to (see mesh.components). Saved only when used, so a project that
    # uses neither is saved exactly as before.
    links: dict = field(default_factory=dict)
    component: str = ""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "params": self.params,
            "transform": np.asarray(self.transform, dtype=np.float64).tolist(),
            "color": self.color,
            "is_hole": self.is_hole,
            "visible": self.visible,
            "fit": self.fit,
        }
        if self.links:
            d["links"] = dict(self.links)
        if self.component:
            d["component"] = self.component
        return d

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
            fit=d.get("fit", DEFAULT_FIT) if d.get("fit") in FITS else DEFAULT_FIT,
            links={str(k): str(v) for k, v in (d.get("links") or {}).items()},
            component=str(d.get("component") or ""),
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
    fit_clearances: dict = field(default_factory=lambda: dict(DEFAULT_FIT_CLEARANCES))
    # Expert mode: the named parameters ({"name", "formula", "note"}; see
    # mesh.parameters). Saved only when there are some.
    parameters: list = field(default_factory=list)
    # Expert mode: the components ({"id", "name"}; see mesh.components)
    # and the history list, once the project keeps one (see mesh.history).
    # Each is saved only when there is one.
    components: list = field(default_factory=list)
    history: dict | None = None

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
            "fit_clearances": dict(self.fit_clearances),
            **({"parameters": [dict(p) for p in self.parameters]} if self.parameters else {}),
            **({"components": [dict(c) for c in self.components]} if self.components else {}),
            **({"history": self.history} if self.history is not None else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(
            shapes=[Shape.from_dict(s) for s in d.get("shapes", [])],
            selection=list(d.get("selection", [])),
            build_volume=tuple(d.get("build_volume", DEFAULT_BUILD_VOLUME)),
            snap_mm=d.get("snap_mm", DEFAULT_SNAP_MM),
            fit_clearances=_read_fit_clearances(d.get("fit_clearances")),
            parameters=[{"name": str(p["name"]), "formula": str(p["formula"]), "note": str(p.get("note", ""))}
                        for p in d.get("parameters") or []],
            components=_read_components(d.get("components")),
            history=_read_history(d.get("history")),
        )


def _read_components(raw):
    from mesh import components

    return components.read(raw)


def _read_history(raw):
    from mesh import history

    return history.read(raw)


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
        # What each undo and redo step was ("add", "group", ...), in step
        # with _undo and _redo, for the window's visible history.
        self.undo_labels: list[str] = []
        self.redo_labels: list[str] = []
        # Bumped by every snapshot/undo/redo -- i.e. every point where the
        # scene identity actually changes. Callers that want to avoid
        # redoing expensive work (printcheck.check's manifold evaluation)
        # when nothing has changed can cache against this instead of
        # re-deriving a content hash of the whole scene themselves.
        self.revision = 0
        # Expert mode's history list (see mesh.history): whether snapshots
        # add steps to it (off while the history itself is changed or
        # worked out again), the tool call the next step is made by, and
        # the scene before the newest step, which settle() compares with
        # the scene now to work out what that step changed.
        self.recording = True
        self.calling = False
        self.pending_call = None
        self._step_before = None
        # The scene before the newest change (None after an undo or redo),
        # so the window can tell what that change replaced (see
        # mesh.components.carry_over).
        self.action_before = None

    def snapshot(self, label: str = "") -> None:
        self.settle()
        self._step_before = None
        self._undo.append(copy.deepcopy(self.scene))
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()
        self.undo_labels.append(label)
        del self.undo_labels[:-HISTORY_LIMIT]
        self.redo_labels.clear()
        self.revision += 1
        self.action_before = self._undo[-1]
        if self.recording and self.scene.history is not None:
            self.scene.history["steps"].append({"label": label, "call": self.pending_call, "effect": None})
            self.pending_call = None
            self._step_before = self._undo[-1]

    def settle(self) -> None:
        """Work out what the newest history step has changed so far, from
        the scene before it to the scene now. Done before the next step,
        an undo or redo, saving, and showing the history."""
        history = self.scene.history
        if self._step_before is None or history is None or not history["steps"]:
            return
        from mesh.history import changes

        history["steps"][-1]["effect"] = changes(self._step_before, self.scene)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.settle()
        self._step_before = self.action_before = None
        self._redo.append(copy.deepcopy(self.scene))
        self.scene = self._undo.pop()
        if self.undo_labels:
            self.redo_labels.append(self.undo_labels.pop())
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._step_before = self.action_before = None
        self._undo.append(copy.deepcopy(self.scene))
        self.scene = self._redo.pop()
        if self.redo_labels:
            self.undo_labels.append(self.redo_labels.pop())
        self.revision += 1
        return True


def _signed_scale(r: np.ndarray) -> np.ndarray:
    """Column lengths of a 3x3 rotation*scale block, with a mirror's sign
    folded onto the X scale rather than lost.

    A shape mirrored by mesh.ops.mirror() ends up with a rotation block
    whose determinant is negative (a reflection, not a proper rotation).
    Column norms alone are always positive, so normalizing by them turns
    that reflection into an ordinary-looking rotation — which is exactly
    the bug this fixes: it made a mirrored cube's inspector angles look
    like a plain 180-degree turn, and typing those angles back silently
    un-mirrored it. Putting the negative sign on the X scale instead keeps
    the decomposition invertible: dividing r by this signed scale always
    yields a proper rotation (determinant +1), and multiplying that
    rotation back by the same signed scale reproduces r exactly.
    """
    sx = np.linalg.norm(r[:, 0])
    sy = np.linalg.norm(r[:, 1])
    sz = np.linalg.norm(r[:, 2])
    sx = sx if sx > 1e-12 else 1.0
    sy = sy if sy > 1e-12 else 1.0
    sz = sz if sz > 1e-12 else 1.0
    if np.linalg.det(r) < 0.0:
        sx = -sx
    return np.array([sx, sy, sz])


def euler_from_transform(m) -> tuple[float, float, float]:
    """Extract (rx, ry, rz) degrees from a 4x4 transform.

    Convention: the rotation part is R = Rz(rz) @ Ry(ry) @ Rx(rx) — i.e. a
    column vector is rotated about X first, then Y, then Z (extrinsic X-Y-Z
    rotation order, sometimes called intrinsic Z-Y-X). Scale is tolerated:
    each column of the rotation block is normalized by its own (signed,
    see _signed_scale) length before angles are extracted, so this works
    on transforms produced by transform_with_euler() below (translation +
    rotation + uniform or per-axis scale, no shear) as well as on a
    mirrored shape's reflection.

    Gimbal lock (ry = +/-90 degrees) is handled without raising: rz is
    pinned to 0 and rx absorbs the coupled rotation, matching what
    transform_with_euler(m, rx, 0.0, +/-90.0) would produce.
    """
    m = np.asarray(m, dtype=np.float64)
    r = m[:3, :3]

    rot = r / _signed_scale(r)

    sin_ry = np.clip(-rot[2, 0], -1.0, 1.0)
    ry = np.arcsin(sin_ry)
    cos_ry = np.cos(ry)

    if abs(cos_ry) > 1e-6:
        rx = np.arctan2(rot[2, 1], rot[2, 2])
        rz = np.arctan2(rot[1, 0], rot[0, 0])
    else:
        rz = 0.0
        rx = np.arctan2(-rot[1, 2], rot[1, 1])

    return tuple(float(v) for v in np.degrees([rx, ry, rz]))


def transform_with_euler(m, rx: float, ry: float, rz: float) -> np.ndarray:
    """Return a new 4x4 transform with rotation (rx, ry, rz) degrees.

    Uses the same convention as euler_from_transform(): R = Rz @ Ry @ Rx.
    Translation and per-axis scale (the signed column lengths of the
    existing rotation block — see _signed_scale) are preserved; only the
    rotation itself is replaced. Preserving the sign, not just the
    magnitude, is what keeps this the exact inverse of
    euler_from_transform() for a mirrored shape: reading a mirrored cube's
    angles and typing them straight back must reproduce the same
    reflection rather than silently un-mirroring it.
    """
    m = np.asarray(m, dtype=np.float64)
    translation = m[:3, 3].copy()
    r = m[:3, :3]

    scale = _signed_scale(r)

    rxr, ryr, rzr = np.radians([rx, ry, rz])
    cx, sx = np.cos(rxr), np.sin(rxr)
    cy, sy = np.cos(ryr), np.sin(ryr)
    cz, sz = np.cos(rzr), np.sin(rzr)

    rot_x = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    rot_y = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rot_z = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])

    rotation = rot_z @ rot_y @ rot_x

    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = rotation * scale
    out[:3, 3] = translation
    return out
