"""Named parameters (Expert mode's Change Parameters and Link Sizes).

A parameter is a name and a formula: a plain number ("40") or arithmetic
on numbers and other parameters ("width / 2 + wall"). A part's size,
position or turn can be linked to a formula; whenever the parameters
change, every linked number is worked out again and the parts follow.

The table lives on the scene (Scene.parameters, a list of {"name",
"formula", "note"}) and each part's links on the part (Shape.links,
field -> formula), so both are saved in the project and undone with it.
Formulas are read by a small calculator of our own, never by Python's
eval: only numbers, names, + - * / ** and brackets, and the functions in
FUNCTIONS.
"""

import ast
import math
import re

import numpy as np

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


def linkable(shape) -> list[str]:
    """The numbers of `shape` that can follow a formula: where it is, how
    it is turned, and its own size numbers."""
    fields = list(POSITION) + list(TURN)
    if shape.kind == "primitive" and not is_reference(shape):
        info = PRIMITIVES.get(shape.params.get("primitive"), {})
        fields += [key for key, default in info.get("defaults", {}).items()
                   if isinstance(default, (int, float)) and not isinstance(default, bool)]
    return fields


def current(shape, field: str) -> float:
    """The number `field` has now."""
    transform = np.asarray(shape.transform, dtype=np.float64)
    if field in POSITION:
        return float(transform[POSITION.index(field), 3])
    if field in TURN:
        return float(euler_from_transform(transform)[TURN.index(field)])
    return float(shape.params[field])


WORDS = {
    "x": "left/right position", "y": "forward/back position", "z": "height above the workplane",
    "rx": "tilt around X", "ry": "tilt around Y", "rz": "turn",
}


def field_words(field: str) -> str:
    return WORDS.get(field, field.replace("_", " "))


def _allowed(shape, field: str, number: float) -> None:
    if field in POSITION or field in TURN or field in MAY_BE_NEGATIVE:
        fits = -LIMIT <= number <= LIMIT
    elif field in MAY_BE_ZERO:
        fits = 0.0 <= number <= LIMIT
    else:
        fits = 0.0 < number <= LIMIT
    if not fits:
        raise ParameterError(f"{shape.name}'s {field_words(field)} would be {number:g}, which it can't be.")


def set_number(shape, field: str, number: float) -> None:
    """Put `number` into `field` of `shape` (no check)."""
    if field in POSITION:
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
