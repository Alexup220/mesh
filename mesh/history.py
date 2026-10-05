"""The history list (Expert mode's Modify > History).

Once a project keeps a history, every change to it is a step in a list,
in order. A step can be changed (a tool's settings) or removed, and then
every step is worked out again from where the history started, so the
parts later tools made follow, as in Fusion's timeline.

The history lives on the scene (Scene.history), so it is saved in the
project and undone with it:

    {"base": the scene (as a dict) when the history started,
     "steps": [{"label", "call", "effect"}, ...]}

- "call" is set for the tools that can run again (the window methods
  marked @replayable): {"method", "args": its settings, "picked": the ids
  selected, in the order picked, "faces": where each clicked face was}.
  Such a step runs the tool again; a clicked face is found again by the
  way it faces and where it was (find_face).
- "off" (only when true) marks a step that is skipped: the project is
  worked out as if it weren't there, but it stays in the list, ready to
  be used again.
- "effect" is what the step changed (changes): the shapes it added
  (whole), the ones it removed, and for each one it changed the fields
  that changed. A change of position is kept as the move itself, so
  replayed it moves the shape from wherever it is by then. A step with no
  call (adding a shape, typing in the Details panel, dragging) replays
  its effect.

Document records the steps (Document.snapshot and settle); the window
replays them (mesh.history_actions).
"""

import copy
import functools
import inspect

import numpy as np

from mesh.scene import Shape
from mesh.shapes import shape_geometry

# The fields of a shape a step can change, besides its params and place.
SHAPE_FIELDS = ("name", "kind", "color", "is_hole", "visible", "fit", "links", "component")
# The scene's own settings a step can change. The parameters are not
# among them: they hold for the whole history (see mesh.parameters).
SETTINGS = ("build_volume", "snap_mm", "fit_clearances", "components")

# Steps' labels in plain words, where the label alone isn't.
WORDS = {
    "": "Change",
    "add": "Add",
    "edit": "Change in Details",
    "union": "Join",
    "difference": "Cut out",
    "intersection": "Keep overlap",
    "hole": "Solid or Hole",
    "push/pull": "Push or pull",
    "fit clearances": "Change fits",
}

FACE_TURNED = 0.999  # a face found again faces within about 2.5 degrees of the one clicked


class HistoryError(ValueError):
    """A step that can't be worked out again; the message says why."""


def start(scene) -> dict:
    """A new, empty history starting from `scene` as it is."""
    base = copy.deepcopy(scene.to_dict())
    for key in ("history", "parameters", "selection"):
        base.pop(key, None)
    return {"base": base, "steps": []}


# --- What a step changed ----------------------------------------------------------------


def _same(a, b) -> bool:
    try:
        return bool(a == b)
    except ValueError:  # numbers in arrays
        return np.array_equal(np.asarray(a), np.asarray(b))


def _setting(scene, key):
    value = getattr(scene, key, None)
    return list(value) if isinstance(value, tuple) else value


def _shape_changes(old, new) -> dict:
    diff = {f: copy.deepcopy(getattr(new, f)) for f in SHAPE_FIELDS
            if not _same(getattr(old, f), getattr(new, f))}
    changed = {k: v for k, v in new.params.items() if k not in old.params or not _same(old.params[k], v)}
    if changed:
        diff["params"] = copy.deepcopy(changed)
    dropped = [k for k in old.params if k not in new.params]
    if dropped:
        diff["drop"] = dropped
    before = np.asarray(old.transform, dtype=np.float64)
    after = np.asarray(new.transform, dtype=np.float64)
    if not np.array_equal(before, after):
        diff["move"] = (after @ np.linalg.inv(before)).tolist()
    return diff


def changes(before, after) -> dict:
    """What turned scene `before` into scene `after`."""
    old = {s.id: s for s in before.shapes}
    now = {s.id for s in after.shapes}
    added = [copy.deepcopy(s.to_dict()) for s in after.shapes if s.id not in old]
    removed = [s.id for s in before.shapes if s.id not in now]
    changed = {}
    for shape in after.shapes:
        if shape.id in old:
            diff = _shape_changes(old[shape.id], shape)
            if diff:
                changed[shape.id] = diff
    settings = {key: copy.deepcopy(_setting(after, key)) for key in SETTINGS
                if not _same(_setting(before, key), _setting(after, key))}
    # What the history list names the step by: the parts it made or
    # changed, or else the ones it removed.
    names = ([d["name"] for d in added] + [s.name for s in after.shapes if s.id in changed]
             or [old[i].name for i in removed])
    return {"added": added, "removed": removed, "changed": changed, "settings": settings,
            "names": names}


GONE = "a part it changes is no longer there."
USED_GONE = "a part it was used on is no longer there."
MADE_LATER = "a part it uses is only made by a later step."


def apply_changes(scene, effect: dict) -> None:
    """Do to `scene` what a step with no call did."""
    present = {s.id for s in scene.shapes}
    scene.remove([i for i in effect.get("removed", []) if i in present])
    for shape_id, diff in effect.get("changed", {}).items():
        try:
            shape = scene.get(shape_id)
        except KeyError:
            raise HistoryError(GONE) from None
        for field in SHAPE_FIELDS:
            if field in diff:
                setattr(shape, field, copy.deepcopy(diff[field]))
        if "params" in diff or "drop" in diff:
            params = {k: v for k, v in shape.params.items() if k not in diff.get("drop", ())}
            params.update(copy.deepcopy(diff.get("params", {})))
            shape.params = params
        if "move" in diff:
            shape.transform = np.asarray(diff["move"], dtype=np.float64) @ np.asarray(shape.transform)
    present = {s.id for s in scene.shapes}
    for data in effect.get("added", []):
        if data["id"] in present:
            raise HistoryError("a part it adds is already there.")
        scene.add(Shape.from_dict(copy.deepcopy(data)))
    for key, value in effect.get("settings", {}).items():
        value = copy.deepcopy(value)
        setattr(scene, key, tuple(value) if key == "build_volume" else value)


def made_later(step: dict, later_steps, present, faces=()) -> bool:
    """Whether `step` uses a part that isn't in the project yet (`present`
    being the ids there now) but that one of `later_steps` makes: a step
    moved before the one that makes its part. `faces` is its tool's
    clicked-face specs (see replayable)."""
    call, effect = step.get("call"), step.get("effect") or {}
    if call is not None:
        used = set(call["picked"]) | {_face_args(spec, call["args"])[0] for spec in faces}
    else:
        used = set(effect.get("changed", {})) | set(effect.get("removed", []))
    made = {d["id"] for s in later_steps if not s.get("off") for d in (s.get("effect") or {}).get("added", [])}
    return bool((used - set(present)) & made)


def rename_added(scene, before_ids, recorded: list) -> None:
    """Give the shapes a replayed tool just added the ids they had when
    the step was recorded, in order, so later steps still find them."""
    made = [s for s in scene.shapes if s.id not in before_ids]
    taken = {s.id for s in scene.shapes}
    for shape, wanted in zip(made, recorded):
        if shape.id == wanted or wanted in taken:
            continue
        scene.selection = [wanted if i == shape.id else i for i in scene.selection]
        taken.discard(shape.id)
        shape.id = wanted
        taken.add(wanted)


# --- Recording a tool's call ------------------------------------------------------------


def plain(value):
    """`value` as numbers, text, lists and dicts (what a project file holds)."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    raise TypeError(f"can't keep {type(value).__name__}")


def _face_args(spec, args):
    """(shape id, face index) of a clicked-face spec: an (id argument,
    face argument) pair, or one argument holding (id, face)."""
    if isinstance(spec, str):
        held = args.get(spec)
        return (held[0], held[1]) if held is not None else (None, None)
    return args.get(spec[0]), args.get(spec[1])


def face_hint(shape, face_index: int, clearances) -> dict | None:
    """Where triangle `face_index` of `shape` is and which way it faces."""
    tm = shape_geometry(shape, clearances)
    if not 0 <= face_index < len(tm.faces):
        return None
    return {"centre": tm.triangles_center[face_index].tolist(),
            "normal": tm.face_normals[face_index].tolist()}


def find_face(shape, face_index: int, hint: dict, clearances):
    """The triangle of `shape` (as it is now) that the face clicked when
    the step was recorded has become: (index, how far it moved).

    Of the triangles facing the same way, those on the flat face nearest
    the recorded one; the same triangle number if it is among them (a part
    whose sizes changed keeps its triangles' order), else the nearest."""
    tm = shape_geometry(shape, clearances)
    normal = np.asarray(hint["normal"], dtype=np.float64)
    centre = np.asarray(hint["centre"], dtype=np.float64)
    facing = np.flatnonzero(tm.face_normals @ normal > FACE_TURNED)
    if len(facing) == 0:
        raise HistoryError(f"the face it was used on is no longer on {shape.name}.")
    centres = tm.triangles_center
    heights = centres[facing] @ normal
    nearest = heights[np.argmin(np.abs(heights - centre @ normal))]
    on_face = facing[np.abs(heights - nearest) < 1e-4]
    if face_index in on_face:
        index = int(face_index)
    else:
        index = int(on_face[np.argmin(np.linalg.norm(centres[on_face] - centre, axis=1))])
    return index, centres[index] - centre


def placed_args(call: dict, faces, scene, clearances) -> dict:
    """The recorded settings of `call`, with each clicked face (and a
    clicked point on it) found again on the parts as they are now."""
    args = copy.deepcopy(call["args"])
    for spec, hint in zip(faces, call.get("faces") or []):
        shape_id, index = _face_args(spec, args)
        if hint is None or shape_id is None:
            continue
        try:
            shape = scene.get(shape_id)
        except KeyError:
            raise HistoryError(USED_GONE) from None
        index, moved = find_face(shape, int(index), hint, clearances)
        if isinstance(spec, str):
            args[spec] = [shape_id, index] + list(args[spec][2:])
        else:
            args[spec[1]] = index
        if args.get("point") is not None:
            args["point"] = (np.asarray(args["point"], dtype=np.float64) + moved).tolist()
    return args


def replayable(*faces):
    """Mark a window method as a tool the history can run again. `faces`
    names its clicked faces: (id argument, face argument) pairs, or the
    name of one argument holding (id, face).

    While the project keeps a history, the outermost such call is noted on
    the document, and the snapshot the method takes records it with its
    step."""

    def wrap(method):
        signature = inspect.signature(method)

        @functools.wraps(method)
        def run(window, *args, **kwargs):
            document = window.document
            if document.calling or not document.recording or document.scene.history is None:
                return method(window, *args, **kwargs)
            document.calling = True
            try:
                document.pending_call = _call(document.scene, method.__name__, signature, faces,
                                              (window, *args), kwargs)
                return method(window, *args, **kwargs)
            finally:
                document.calling = False
                document.pending_call = None

        run.replay_faces = faces
        return run

    return wrap


def _call(scene, name: str, signature, faces, args, kwargs) -> dict | None:
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    try:
        settings = plain(dict(list(bound.arguments.items())[1:]))
    except TypeError:
        return None  # settings a file can't hold: the step replays its effect
    hints = []
    for spec in faces:
        shape_id, index = _face_args(spec, settings)
        try:
            hints.append(face_hint(scene.get(shape_id), int(index), scene.fit_clearances))
        except (KeyError, TypeError, ValueError):
            hints.append(None)
    return {"method": name, "args": settings, "picked": list(scene.selection), "faces": hints}


# --- Showing a step ---------------------------------------------------------------------


def label_words(label: str) -> str:
    words = WORDS.get(label, label)
    return words[:1].upper() + words[1:]


def describe(step: dict) -> str:
    """A step in the history list: what it did, and to which parts."""
    text = label_words(step.get("label", ""))
    names = list(dict.fromkeys((step.get("effect") or {}).get("names", [])))
    if names:
        shown = ", ".join(names[:3])
        if len(names) > 3:
            shown += f" and {len(names) - 3} more"
        text += f": {shown}"
    return text + " (skipped)" if step.get("off") else text


def read(raw) -> dict | None:
    """A history from a project file, or None if it isn't one."""
    if not isinstance(raw, dict) or not isinstance(raw.get("base"), dict) \
            or not isinstance(raw.get("steps"), list):
        return None
    steps = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            return None
        call, effect = step.get("call"), step.get("effect")
        if call is not None and not (isinstance(call, dict) and isinstance(call.get("method"), str)
                                     and isinstance(call.get("args"), dict)):
            return None
        if effect is not None and not isinstance(effect, dict):
            return None
        kept = {"label": str(step.get("label", "")), "call": call, "effect": effect}
        if step.get("off") is True:
            kept["off"] = True
        steps.append(kept)
    return {"base": raw["base"], "steps": steps}
