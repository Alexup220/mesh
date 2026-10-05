"""Components (Expert mode's Assemble menu): separate parts kept together
under a name, as in Fusion, without joining them into one solid.

The scene lists its components (Scene.components, [{"id", "name"}]) and
each part names the one it belongs to (Shape.component, "" for none), so
both are saved in the project and undone with it. A part belongs to at
most one component, and components don't hold other components.

A component's id is worked out from what it was made from (new_id), not
drawn at random, so working a history out again (mesh.history) gives the
same component the same id, and later steps still find it.
"""

import uuid

from mesh import ops

NAME_LIMIT = 60
_IDS = uuid.UUID("6f1c2a3e-58a4-4c1b-9d0e-3f7b2c9a1d55")


class ComponentError(ValueError):
    """A component change that can't be made; the message says why."""


def new_id(seed: str, taken) -> str:
    """The id for a component made from `seed`, not one of `taken`."""
    made = uuid.uuid5(_IDS, seed).hex
    while made in taken:
        made = uuid.uuid5(_IDS, made).hex
    return made


def next_name(components, start: str = "Component") -> str:
    """"Component 1", "Component 2", ...: the first not yet used."""
    names = {c["name"] for c in components}
    number = 1
    while f"{start} {number}" in names:
        number += 1
    return f"{start} {number}"


def check_name(name, components, own_id: str | None = None) -> str:
    """`name`, tidied, if a component can be called it."""
    name = " ".join(str(name).split())
    if not name:
        raise ComponentError("A component needs a name.")
    if len(name) > NAME_LIMIT:
        raise ComponentError(f"A component's name can be at most {NAME_LIMIT} letters long.")
    if any(c["name"] == name and c["id"] != own_id for c in components):
        raise ComponentError(f"There is already a component called \"{name}\".")
    return name


def get(components, component_id: str) -> dict:
    for component in components:
        if component["id"] == component_id:
            return component
    raise ComponentError("That component is no longer there.")


def members(shapes, component_id: str) -> list:
    return [s for s in shapes if s.component == component_id]


def shown(shapes, component_id: str) -> bool:
    """Whether any of the component's parts shows (an empty one counts as shown)."""
    parts = members(shapes, component_id)
    return not parts or any(s.visible for s in parts)


def describe(component: dict, shapes) -> str:
    """A component in the Components list: its name, how many parts, and
    whether it is hidden."""
    count = len(members(shapes, component["id"]))
    text = f"{component['name']}: " + ("no parts" if count == 0 else "1 part" if count == 1 else f"{count} parts")
    return text if shown(shapes, component["id"]) else text + " (hidden)"


def read(raw) -> list:
    """The components from a project file; anything that isn't one is left out."""
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] not in seen:
            out.append({"id": item["id"], "name": str(item.get("name") or "Component")})
            seen.add(item["id"])
    return out


def carry_over(before, after) -> list:
    """A tool that replaced parts of one component (Round an Edge, Combine,
    Group, an Extrude from its sketch ...) puts what it made in that
    component too. Returns the parts that joined one."""
    old = {s.id: s for s in before.shapes}
    now = {s.id for s in after.shapes}
    left = {s.component for s in before.shapes if s.id not in now and s.component}
    if len(left) != 1:
        return []
    component = left.pop()
    if component not in {c["id"] for c in after.components}:
        return []
    joined = [s for s in after.shapes if s.id not in old and not s.component]
    for shape in joined:
        shape.component = component
    return joined


def copied(shapes, components, component_id: str, offset=(10.0, 10.0, 0.0)):
    """An independent copy of a component: (the new component, copies of
    its parts, moved by `offset`)."""
    source = get(components, component_id)
    parts = members(shapes, component_id)
    if not parts:
        raise ComponentError(f"{source['name']} has no parts to copy.")
    made = {"id": new_id(f"{component_id}/copy", {c["id"] for c in components}),
            "name": next_name(components, f"{source['name']} copy")}
    copies = [ops.duplicate(part, offset) for part in parts]
    for part in copies:
        part.component = made["id"]
    return made, copies
