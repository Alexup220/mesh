"""Named parameters (Expert mode's Change Parameters and Link Sizes).

A parameter is a name and a formula: a plain number ("40") or arithmetic
on numbers and other parameters ("width / 2 + wall"). A part's size,
position or turn can be linked to a formula; whenever the parameters
change, every linked number is worked out again and the parts follow.

The table lives on the scene (Scene.parameters, a list of {"name",
"formula", "note"}) and each part's links on the part (Shape.links,
field -> formula), so both are saved in the project and undone with it.
A sketch's curves, and those a part made from a sketch keeps, can be
linked too: field "curve2.width" is the second curve's width,
"curve1.corner.x" its corner's X, "curve3.points.2.y" a spline's second
point's Y.
Formulas are read by a small calculator of our own, never by Python's
eval: only numbers, names, + - * / ** and brackets, and the functions in
FUNCTIONS.
"""

import ast
import math
import re

import numpy as np

from mesh import sketch
from mesh.scene import euler_from_transform, transform_with_euler
from mesh.shapes import PRIMITIVES, is_reference

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _degrees(fn):
    return lambda angle: fn(math.radians(angle))


# Angles in degrees, like everywhere else in mesh.
FUNCTIONS = {
    "min": min, "max": max, "abs": abs, "round": round, "sqrt": math.sqrt,
    "sin": _degrees(math.sin), "cos": _degrees(math.cos), "tan": _degrees(math.tan),
}
CONSTANTS = {"pi": math.pi}
RESERVED = set(FUNCTIONS) | set(CONSTANTS)

POSITION = ("x", "y", "z")
TURN = ("rx", "ry", "rz")
# Numbers that may be 0 (none) or less than 0; every other size must be
# more than 0.
MAY_BE_ZERO = ("radius", "chamfer")
MAY_BE_NEGATIVE = ("taper", "twist")
LIMIT = 10000.0  # mm, as in the Details panel
CURVE = re.compile(r"curve([1-9][0-9]*)\.([a-z_]+(?:\.[0-9]+)?(?:\.[xy])?)\Z")
CURVE_SIZES = ("width", "height", "diameter", "radius")


class ParameterError(ValueError):
    """A parameter or link that can't be worked out; the message says why."""


_OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b,
    ast.Mod: lambda a, b: a % b,
}


def _parse(formula: str) -> ast.AST:
    text = str(formula).strip()
    if not text:
        raise ParameterError("A formula can't be empty.")
    try:
        return ast.parse(text.replace("^", "**"), mode="eval").body
    except SyntaxError as exc:
        raise ParameterError(f"\"{text}\" can't be read as a formula.") from exc


def names_in(formula: str) -> set[str]:
    """The parameter names a formula uses."""
    found = set()
    for node in ast.walk(_parse(formula)):
        if isinstance(node, ast.Name) and node.id not in RESERVED:
            found.add(node.id)
    return found


def evaluate(formula: str, known: dict) -> float:
    """The number a formula comes to, given the parameters' values."""
    text = str(formula).strip()

    def value(node) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            if node.id not in known:
                raise ParameterError(f"\"{text}\" uses \"{node.id}\", which is not a parameter.")
            return float(known[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            inner = value(node.operand)
            return inner if isinstance(node.op, ast.UAdd) else -inner
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = value(node.left), value(node.right)
            try:
                return float(_OPERATORS[type(node.op)](left, right))
            except ZeroDivisionError as exc:
                raise ParameterError(f"\"{text}\" divides by zero.") from exc
            except OverflowError as exc:
                raise ParameterError(f"\"{text}\" comes to a number too big to use.") from exc
            except TypeError as exc:
                raise ParameterError(f"\"{text}\" does not come to a number.") from exc
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS \
                and not node.keywords and node.args:
            try:
                return float(FUNCTIONS[node.func.id](*(value(a) for a in node.args)))
            except (TypeError, ValueError) as exc:
                raise ParameterError(f"\"{text}\" uses {node.func.id} in a way that doesn't work.") from exc
        raise ParameterError(f"\"{text}\" can't be read as a formula.")

    result = value(_parse(text))
    if not math.isfinite(result):
        raise ParameterError(f"\"{text}\" does not come to a number.")
    return result


def check_name(name: str) -> None:
    if not NAME.match(str(name)):
        raise ParameterError(f"\"{name}\" can't be a parameter name: use letters, digits and _, "
                             "starting with a letter.")
    if name in RESERVED:
        raise ParameterError(f"\"{name}\" is already used in formulas (min, max, abs, round, sqrt, sin, cos, tan, pi).")


def values(parameters) -> dict:
    """Every parameter's number, worked out in the order they need each
    other. Refuses unknown names, repeated names and parameters that
    (through others) need themselves."""
    formulas = {}
    for row in parameters:
        name = str(row["name"]).strip()
        check_name(name)
        if name in formulas:
            raise ParameterError(f"There are two parameters called \"{name}\".")
        formulas[name] = str(row["formula"])
    needs = {name: names_in(formula) for name, formula in formulas.items()}
    known: dict = {}
    working: list = []

    def work_out(name):
        if name in known:
            return
        if name in working:
            loop = " → ".join(working[working.index(name):] + [name])
            raise ParameterError(f"These parameters need each other, so none can be worked out: {loop}.")
        working.append(name)
        for other in needs[name]:
            if other in formulas:
                work_out(other)
        known[name] = evaluate(formulas[name], known)
        working.pop()

    for name in formulas:
        work_out(name)
    return known


# --- Links -------------------------------------------------------------------------


def curve_fields(entities) -> list[str]:
    """The numbers of a sketch's curves that can follow a formula."""
    fields = []
    for n, entity in enumerate(entities, 1):
        for key, value in entity.items():
            if key == "type" or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                fields.append(f"curve{n}.{key}")
            elif key == "points":
                fields += [f"curve{n}.points.{m}.{axis}" for m in range(1, len(value) + 1) for axis in "xy"]
            elif isinstance(value, list) and len(value) == 2:
                fields += [f"curve{n}.{key}.x", f"curve{n}.{key}.y"]
    return fields


def linkable(shape) -> list[str]:
    """The numbers of `shape` that can follow a formula: where it is, how
    it is turned, its own size numbers, and its sketch's curves."""
    fields = list(POSITION) + list(TURN)
    if shape.kind == "primitive" and not is_reference(shape):
        info = PRIMITIVES.get(shape.params.get("primitive"), {})
        fields += [key for key, default in info.get("defaults", {}).items()
                   if isinstance(default, (int, float)) and not isinstance(default, bool)]
    if shape.kind == "primitive" and isinstance(shape.params.get("entities"), list):
        fields += curve_fields(shape.params["entities"])
    return fields


def _curve_place(field: str):
    """(curve index from 0, path into the curve) of a curve field, or None."""
    match = CURVE.match(field)
    if match is None:
        return None
    path = [int(p) - 1 if p.isdigit() else {"x": 0, "y": 1}.get(p, p) for p in match.group(2).split(".")]
    return int(match.group(1)) - 1, path


def _curve_number(entities, place):
    index, path = place
    value = entities[index]
    for step in path:
        value = value[step]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KeyError(path)
    return value


def current(shape, field: str) -> float:
    """The number `field` has now."""
    transform = np.asarray(shape.transform, dtype=np.float64)
    if field in POSITION:
        return float(transform[POSITION.index(field), 3])
    if field in TURN:
        return float(euler_from_transform(transform)[TURN.index(field)])
    place = _curve_place(field)
    if place is not None:
        return float(_curve_number(shape.params["entities"], place))
    return float(shape.params[field])


WORDS = {
    "x": "left/right position", "y": "forward/back position", "z": "height above the workplane",
    "rx": "tilt around X", "ry": "tilt around Y", "rz": "turn",
}


CURVE_WORDS = {"corner": "corner", "centre": "centre", "start": "start point", "end": "end point"}
CURVE_NUMBER_WORDS = {"width": "width (mm)", "height": "height (mm)", "diameter": "diameter (mm)",
                      "radius": "radius (mm)", "sides": "sides"}


def field_words(field: str) -> str:
    place = _curve_place(field)
    if place is not None:
        index, path = place
        if path[0] == "points":
            words = [f"point {path[1] + 1}", "X" if path[2] == 0 else "Y"]
        else:
            words = [path[0].replace("_", " ")] + (["X" if path[1] == 0 else "Y"] if len(path) == 2 else [])
        return f"curve {index + 1} " + " ".join(words)
    return WORDS.get(field, field.replace("_", " "))


def curve_label(shape, field: str) -> str:
    """A curve field's label in a form: "Curve 2 (circle): diameter (mm)"."""
    index, path = _curve_place(field)
    kind = shape.params["entities"][index].get("type", "curve")
    key = path[0]
    if key == "points":
        words = f"point {path[1] + 1} {'X' if path[2] == 0 else 'Y'} (mm)"
    elif len(path) == 2:
        words = f"{CURVE_WORDS.get(key, key)} {'X' if path[1] == 0 else 'Y'} (mm)"
    elif key in CURVE_NUMBER_WORDS:
        words = CURVE_NUMBER_WORDS[key]
    elif kind == "arc":
        words = f"{key} angle (degrees)"
    else:
        words = "turn (degrees)" if key == "angle" else key.replace("_", " ")
    return f"Curve {index + 1} ({kind}): {words}"


def _allowed(shape, field: str, number: float) -> None:
    place = _curve_place(field)
    if place is not None:
        key = place[1][0]
        if key in CURVE_SIZES:
            fits = 0.0 < number <= LIMIT
        elif key == "sides":
            fits = 3 <= number <= 1000
        else:
            fits = -LIMIT <= number <= LIMIT
    elif field in POSITION or field in TURN or field in MAY_BE_NEGATIVE:
        fits = -LIMIT <= number <= LIMIT
    elif field in MAY_BE_ZERO:
        fits = 0.0 <= number <= LIMIT
    else:
        fits = 0.0 < number <= LIMIT
    if not fits:
        raise ParameterError(f"{shape.name}'s {field_words(field)} would be {number:g}, which it can't be.")


def _set_curve_number(shape, place, number: float) -> None:
    """Put `number` into a curve, which must still be one a sketch can draw."""
    index, path = place
    entities = [dict(e) for e in shape.params["entities"]]
    entity = entities[index] = {k: (list(map(list, v)) if k == "points" else list(v) if isinstance(v, list) else v)
                                for k, v in entities[index].items()}
    holder = entity
    for step in path[:-1]:
        holder = holder[step]
    holder[path[-1]] = int(round(number)) if path == ["sides"] else float(number)
    try:
        entities[index] = sketch.clean_entity(entity)
    except sketch.SketchError as exc:
        raise ParameterError(f"{shape.name}'s curve {index + 1} can't take {number:g} there. {exc}") from None
    shape.params = {**shape.params, "entities": entities}


def set_number(shape, field: str, number: float) -> None:
    """Put `number` into `field` of `shape` (no check, but a curve must
    still be one a sketch can draw)."""
    place = _curve_place(field)
    if place is not None:
        _set_curve_number(shape, place, number)
    elif field in POSITION:
        shape.transform = np.asarray(shape.transform, dtype=np.float64).copy()
        shape.transform[POSITION.index(field), 3] = number
    elif field in TURN:
        angles = list(euler_from_transform(shape.transform))
        angles[TURN.index(field)] = number
        shape.transform = transform_with_euler(shape.transform, *angles)
    else:
        shape.params[field] = float(number)


def check_links(shape, links: dict, known: dict) -> dict:
    """The numbers `links` (field -> formula) give `shape`, checked."""
    fields = set(linkable(shape))
    numbers = {}
    for field, formula in links.items():
        if field not in fields:
            raise ParameterError(f"{shape.name} has no {field_words(field)} to link.")
        number = evaluate(formula, known)
        _allowed(shape, field, number)
        numbers[field] = number
    return numbers


def apply_links(shapes, known: dict) -> list:
    """Set every linked number of `shapes` from the parameters' values
    `known`. Returns the shapes that changed. Turns are set after
    positions, so a linked turn keeps a linked position."""
    changed = []
    for shape in shapes:
        links = getattr(shape, "links", None) or {}
        if not links:
            continue
        numbers = check_links(shape, links, known)
        before = (np.asarray(shape.transform).tobytes(), repr(shape.params))
        for field in sorted(numbers, key=lambda f: (f in TURN, f)):
            set_number(shape, field, numbers[field])
        if (np.asarray(shape.transform).tobytes(), repr(shape.params)) != before:
            changed.append(shape)
    return changed


def users(shapes, name: str) -> list:
    """The shapes with a link that uses parameter `name`."""
    return [s for s in shapes if any(name in names_in(f) for f in (getattr(s, "links", None) or {}).values())]


def links_kept(before, after) -> dict:
    """The links of `before` that still hold once its curves are changed
    to those of `after` (Change Sketch): a link to a curve that is gone,
    or to a number that was changed, ends."""
    kept = {}
    for field, formula in (getattr(before, "links", None) or {}).items():
        if _curve_place(field) is not None:
            try:
                if current(before, field) != current(after, field):
                    continue
            except (KeyError, IndexError, TypeError):
                continue
        kept[field] = formula
    return kept
