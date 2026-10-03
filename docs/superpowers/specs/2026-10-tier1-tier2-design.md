# mesh — Tier 1 + Tier 2 modeling tools: design note

**Date:** 2026-10-03
**Status:** Written before implementation, for review in the PR (not a gate).
**Binding context:** `2026-09-07-mesh-design.md`. Nothing here changes the core
rules: shapes are params + transform, geometry is derived, `Shape.kind` stays
`primitive | imported | group`, core modules stay free of Qt/VTK, every
mutation snapshots first (fallible ones: try first, snapshot only on success),
and no slicer-style print analysis is added.

## Shared plumbing

- **New pure core modules** (all added to `CORE` in `tests/test_purity.py`):
  - `mesh/solids.py`: trimesh <-> manifold3d conversion and small solid
    builders (hulls, extrusions, plane splits). Everything that must come out
    watertight is built through manifold3d.
  - `mesh/hardware.py`: the one hardware dimension table, with sources.
  - `mesh/text.py`: text outlines from a bundled font, extruded.
  - `mesh/builders.py`: multi-part generators (hollow out, split, patterns,
    box with lid).
- **Non-numeric primitive params.** `PRIMITIVES[name]` may carry a `choices`
  map (`{param: [(value, label), ...]}`); the Inspector builds a combo box for
  those, a text box for any other string default, and spin boxes for numbers.
  Primitives can set `"shelf": False` to stay off the shape shelf (hardware
  holes and text have their own menu entries).
- **Picking on a surface.** The viewport gains a pick mode. When one is set, a
  left click reports `(shape id, triangle index, world point)` instead of
  changing the selection. The window turns the triangle index into a world
  direction from the shape's own triangles. Lay flat, Place on face and Measure
  all use this one path. `Esc` leaves any mode.
- **Placing new shapes.** Every "add" action (shelf, hardware, text) goes
  through one helper: snapshot, create, optionally place on a chosen face, add,
  select, sync.

## 1. Fit tolerance

- **Data:** `Shape.fit: str = "exact"` (`exact | press | snug | loose`),
  serialised in `Shape.to_dict`; missing in old files -> `"exact"`.
  `Scene.fit_clearances = {"press": 0.1, "snug": 0.2, "loose": 0.4}`,
  serialised; missing -> defaults. Old projects load unchanged (tested).
- **Logic (core):** `shapes.shape_geometry(shape, clearances=None)`. When the
  shape is a Hole with a non-exact fit, the clearance `c` is added on every
  side: for primitives each size grows by `2c` (radii by `c`) and the shape is
  lowered by `c` so it grows evenly; hardware holes add `c` to every radius and
  both ends. Imported/group holes grow by a per-axis scale about their centre so
  each outside size grows by `2c` (approximate; stated in the README).
  `ops.evaluate/boolean/make_group/make_boolean_group`, `export_scene`,
  `printcheck` and the viewport all pass `scene.fit_clearances`, so they agree.
  A group's stored result is evaluated once, at grouping time.
- **UI:** Inspector "Fit" combo (Exact / Press fit / Snug fit / Loose fit),
  shown only for Holes. Shape menu "Fit clearances..." edits the three values.
- **Undo:** fit edits go through the existing coalesced inspector edit (one
  snapshot per burst). Changing clearances is one snapshot.

## 2. Hardware holes

- **Data:** four new primitives, all hidden from the shelf:
  `screw_hole {size, head, length}`, `nut_trap {size, length}`,
  `insert_pocket {size}`, `magnet_pocket {diameter, depth}`. `size`/`head` are
  choices (combo boxes). Every dimension lives in `mesh/hardware.py` with its
  source; uncertain values carry `# verify`.
- **Logic (core):** `hardware.py` builds each hole with its opening at the top
  (z = height) and its body going down to z = 0, so it can be sunk into a top
  face. Fit clearance is applied inside the builder.
- **UI:** "Add hardware hole" menu: Screw hole (plain / countersunk /
  counterbored) M2-M6, Nut trap M2-M6, Heat-set insert pocket M2-M5, Magnet
  pocket 10x2 / 8x2 / 6x2 / 4x2. Each creates one Hole shape with a default
  fit from the table (screw clearance holes Exact because ISO 273 already
  includes clearance; nut traps Snug; insert pockets Exact because inserts are
  melted into an undersized hole; magnets Press).
- **Undo:** one snapshot per added hole.

## 3. Lay flat

- **Logic (core):** `ops.lay_flat(shape, direction, clearances)` rotates the
  shape about its centre so `direction` points straight down, rewrites the
  transform through `euler_from_transform`/`transform_with_euler`, then
  `ops.drop_to_plane`.
- **UI:** Shape menu "Lay flat on a face" (`L`): with one part selected, the
  next click on that part picks the face. One click, then the mode ends.
- **Undo:** one snapshot when the face click succeeds; none for entering or
  cancelling the mode.

## 4. Place on face

- **Logic (core):** `ops.place_on_face(shape, point, direction)`: turns the
  shape so its "up" matches the face direction and centres its footprint on the
  point. A solid sits on the face; a Hole (hardware, engraved text) is sunk so
  its top is flush with the face.
- **UI:** checkable Shape menu action "Place next shape on a face" (`P`).
  Click a face, then add any shape; the mode ends after one placement. With the
  mode off, shapes land on the workplane as before.
- **Undo:** the add is the one snapshot; picking the face does not snapshot.

## 5. Hollow out

- **Logic (core):** `builders.hollow(shape, wall, open_top, drain, clearances)`
  returns a group (so Ungroup gives back the original). Box, cylinder and
  sphere: the inside is the same primitive inset by the wall thickness (exact);
  open top runs the inside up through the top; the drain hole is a cylinder
  through the bottom centre. Other shapes: the inside is the part shrunk
  evenly by the wall thickness (manifold3d erosion by a sphere, so the wall is
  even to within the sphere's facets), flagged `approximate`; open top is not
  offered for those. Too-thick walls, holes, and too-large drain holes raise a
  plain-language error.
- **UI:** Shape menu "Hollow out...": Wall thickness (mm) default 2, Open top,
  Drain hole (mm) (0 = none). The dialog says plainly when the result will be
  approximate.
- **Undo:** attempt first, one snapshot on success, none on failure.

## 6. Split part

- **Logic (core):** `builders.split(shape, axis, position, pegs, peg_diameter,
  clearances)` cuts the world-space solid with manifold3d's plane split. Each
  half becomes a group (half body + pegs, or half body + Snug-fit peg Holes) so
  it stays editable. Pegs go inside the cut face (placed with shapely, keeping
  a margin from the edge); peg Holes are checked to stay inside their half.
  Both halves are laid flat on their cut face with `ops.lay_flat` and placed
  side by side.
  **Deviation, on purpose:** with pegs on, the peg half is laid with its cut
  face *up* (pegs pointing up). Pegs facing the bed would not print, so
  "cut face down" is kept for every half without pegs.
- **UI:** Shape menu "Split part...": Cut direction (flat / left-right /
  front-back), position (mm), Add alignment pegs, peg size.
- **Undo:** attempt first, one snapshot on success.

## 7. Rounded shapes

- **Data:** primitives `rounded_box {width, depth, height, radius, chamfer}`
  and `rounded_cylinder {diameter, height, radius, chamfer}` (shelf-visible).
- **Logic (core):** rounded box = manifold3d hull of eight corner spheres;
  rounded cylinder = a rounded profile revolved. Radius clamped to half the
  smallest size.
- **UI/Undo:** shelf buttons; inspector fields come from the numeric defaults.

## 8. Bottom chamfer

- **Data:** `chamfer` (default 0) added to the defaults of cube, cylinder,
  rounded_box, rounded_cylinder. Old files without it read as 0.
- **Logic (core):** intersect the shape with a 45-degree "chamfer clip" solid
  (its footprint inset by the chamfer at z = 0, widening at 45 degrees).
  Clamped below the height and half the footprint.
- **UI/Undo:** inspector field "Bottom chamfer (mm)"; normal edit undo.

## 9. Patterns

- **Logic (core):** `builders.repeat_row(shape, count, spacing, axis)` and
  `builders.repeat_circle(shape, count, radius, centre, angle)` (in builders,
  next to the other tools that refuse with a plain `BuildError`) return new copies
  (deep copies, so `is_hole` and `fit` carry over). The circle turns each copy
  about a vertical axis through the centre; the original is moved onto the
  circle at its current angle. `count` includes the original.
- **UI:** Shape menu "Repeat in a row..." and "Repeat in a circle...".
- **Undo:** one snapshot for the whole pattern.

## 10. Box with lid

- **Logic (core):** `builders.box_with_lid(width, depth, height, wall,
  lid_height, fit, clearances)` returns two groups built from box primitives:
  a body (open box, with the inner half of the wall cut away at the top as a
  lip recess) and a lid (plate plus a lip ring sized to the recess minus the fit
  clearance on each side). `height` is the closed box's total height. The lid is
  flipped so its lip points up, and both sit side by side on the workplane.
- **UI:** Shape menu "Box with lid...". **Undo:** attempt first, one snapshot.

## 11. Text

- **Data:** primitive `text {text, letter_height, depth}` (hidden from shelf).
  Raised = solid, engraved = Hole (`is_hole`), so it uses the normal Hole path.
- **Logic (core):** `mesh/text.py` reads glyph outlines with fontTools from a
  font bundled in `mesh/fonts/` (DejaVu Sans, with its licence), flattens
  curves, fills with manifold3d's non-zero rule and extrudes. Never touches
  system fonts. Letter height = height of a capital letter.
- **UI:** Shape menu "Add text..." dialog: text, letter height, depth,
  Raised/Engraved. The inspector edits the text in place.
- **Dependency:** `fonttools` (pure-Python wheel; already installed today as a
  dependency of matplotlib via vtk) pinned as a direct dependency.
- **Undo:** one snapshot per add.

## 12. Measure

- **Logic:** `ops.distance(a, b)`; nothing else touches the scene.
- **UI:** checkable "Measure" action (`M`). Click two points on parts; the
  distance shows in the status bar and as a line in the viewport. Esc or the
  Measure action again exits and removes the line.
- **Undo:** none. Tests assert the undo depth and scene are unchanged.
