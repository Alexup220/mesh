"""Components (Expert mode's Assemble menu): separate parts kept together
under a name, as in Fusion, without joining them into one solid.

The scene lists its components (Scene.components, [{"id", "name"}], plus
"parent" for one inside another) and each part names the one it belongs
to (Shape.component, "" for none), so both are saved in the project and
undone with it. A part belongs to at most one component, and a component
can hold other components, as in Fusion: what is done to a component
(select, show or hide, copy, save for printing) is done to the
components inside it too.

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


def inside(components, component_id: str) -> list[str]:
    """The ids of `component_id` and every component inside it, at any depth."""
    found, todo = [], [component_id]
    while todo:
        current = todo.pop(0)
        if current in found:
            continue
        found.append(current)
        todo += [c["id"] for c in components if c.get("parent") == current]
    return found


def depth(components, component_id: str) -> int:
    """How many components `component_id` is inside."""
    by_id = {c["id"]: c for c in components}
    count, seen = 0, {component_id}
    parent = by_id.get(component_id, {}).get("parent")
    while parent in by_id and parent not in seen:
        seen.add(parent)
        count += 1
        parent = by_id[parent].get("parent")
    return count


def in_tree_order(components) -> list:
    """The components with each one followed by those inside it."""
    known = {c["id"] for c in components}
    out = []
    for top in [c for c in components if c.get("parent") not in known]:
        out += [get(components, i) for i in inside(components, top["id"])]
    return out


def members(shapes, component_id: str, components=()) -> list:
    """The component's parts; with `components` given, also those of the
    components inside it."""
    ids = set(inside(components, component_id)) if components else {component_id}
    return [s for s in shapes if s.component in ids]


def shown(shapes, component_id: str, components=()) -> bool:
    """Whether any of the component's parts shows (an empty one counts as shown)."""
    parts = members(shapes, component_id, components)
    return not parts or any(s.visible for s in parts)


def describe(component: dict, shapes, components=()) -> str:
    """A component in the Components list: its name, how many parts (with
    those of the components inside it), and whether it is hidden."""
    count = len(members(shapes, component["id"], components))
    text = f"{component['name']}: " + ("no parts" if count == 0 else "1 part" if count == 1 else f"{count} parts")
    return text if shown(shapes, component["id"], components) else text + " (hidden)"


def read(raw) -> list:
    """The components from a project file; anything that isn't one is left
    out, and so is a "parent" that isn't another component or that would
    put a component inside itself."""
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] not in seen:
            component = {"id": item["id"], "name": str(item.get("name") or "Component")}
            if isinstance(item.get("parent"), str):
                component["parent"] = item["parent"]
            out.append(component)
            seen.add(item["id"])
    for component in out:
        if "parent" in component and (component["parent"] not in seen or _loops(out, component["id"])):
            del component["parent"]
    return out


def _loops(components, component_id: str) -> bool:
    """Whether going out from `component_id`, parent by parent, comes round
    to a component already passed."""
    by_id = {c["id"]: c for c in components}
    seen, current = set(), component_id
    while current in by_id and "parent" in by_id[current]:
        if current in seen:
            return True
        seen.add(current)
        current = by_id[current]["parent"]
    return False


def can_go_inside(components, component_id: str, parent_id: str | None) -> None:
    """Raise ComponentError if `component_id` can't go inside `parent_id`
    (None: inside nothing)."""
    source = get(components, component_id)
    if parent_id is None:
        if "parent" not in source:
            raise ComponentError(f"{source['name']} is not inside another component.")
        return
    parent = get(components, parent_id)
    if parent_id in inside(components, component_id):
        raise ComponentError(f"{source['name']} can't go inside itself or inside a component it holds.")
    if source.get("parent") == parent_id:
        raise ComponentError(f"{source['name']} is already inside {parent['name']}.")


def put_inside(components, component_id: str, parent_id: str | None) -> list:
    """The components with `component_id` moved inside `parent_id` (None:
    inside nothing). Check with can_go_inside first."""
    out = []
    for component in components:
        if component["id"] == component_id:
            component = {k: v for k, v in component.items() if k != "parent"}
            if parent_id is not None:
                component["parent"] = parent_id
        out.append(component)
    return out


def wholly_selected(selected, shapes, components) -> list:
    """The components every part of which (at any depth) is `selected`,
    leaving out those inside another such one: a new component made from
    the selection holds them whole."""
    chosen = {s.id for s in selected}
    whole = [c["id"] for c in components
             if (parts := members(shapes, c["id"], components)) and all(p.id in chosen for p in parts)]
    by_id = {c["id"]: c for c in components}
    return [i for i in whole if by_id[i].get("parent") not in whole]


def common_parent(selected, components, whole) -> str | None:
    """The component everything selected was directly in (the components
    `whole` and the other parts), when that is one and the same: a new
    component made from them goes inside it."""
    by_id = {c["id"]: c for c in components}
    held = {i for component_id in whole for i in inside(components, component_id)}
    places = {by_id[i].get("parent") for i in whole}
    places |= {s.component or None for s in selected if s.component not in held}
    place = places.pop() if len(places) == 1 else None
    return place if place in by_id else None


def broken_apart(components, component_id: str) -> list:
    """The components without `component_id`; those directly inside it go
    where it was."""
    parent = get(components, component_id).get("parent")
    return put_all_inside([c for c in components if c["id"] != component_id],
                          [c["id"] for c in components if c.get("parent") == component_id], parent)


def put_all_inside(components, ids, parent_id: str | None) -> list:
    for component_id in ids:
        components = put_inside(components, component_id, parent_id)
    return components


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
    """An independent copy of a component and the components inside it:
    (the new components, the copy of `component_id` first; copies of their
    parts, moved by `offset`)."""
    source = get(components, component_id)
    parts = members(shapes, component_id, components)
    if not parts:
        raise ComponentError(f"{source['name']} has no parts to copy.")
    listed, new_ids = list(components), {}
    for old_id in inside(components, component_id):
        old = get(components, old_id)
        made = {"id": new_id(f"{old_id}/copy", {c["id"] for c in listed}),
                "name": next_name(listed, f"{old['name']} copy")}
        parent = new_ids.get(old.get("parent"), old.get("parent"))
        if parent is not None:
            made["parent"] = parent
        new_ids[old_id] = made["id"]
        listed.append(made)
    copies = [ops.duplicate(part, offset) for part in parts]
    for part, original in zip(copies, parts):
        part.component = new_ids[original.component]
    return listed[len(components):], copies
