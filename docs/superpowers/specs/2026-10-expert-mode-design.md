# mesh — Expert mode: design note

**Date:** 2026-10-04
**Status:** Written with Phase 0, for review in the PR. Later phases may refine it.
**Binding context:** `2026-09-07-mesh-design.md`. Nothing here changes the core
rules: shapes are params + transform, geometry is derived, `Shape.kind` stays
`primitive | imported | group`, core modules stay free of Qt/VTK, every mutation
snapshots first (fallible ones: try first, snapshot only on success), no
slicer-style print analysis, and no jargon in user-facing text.

## The switch (Phase 0)

- **One preference, off by default.** `mesh/settings.py` (core) keeps this
  computer's preferences in `$XDG_CONFIG_HOME/mesh/settings.json`
  (`~/.config/mesh/` normally). Expert mode is on only when that file says
  exactly `true`; a missing or damaged file means off. It is never written into
  a `.mesh` project, so opening any project, old or new, leaves it as it was.
- **One place lists the tools.** `mesh/expert.py` (core) holds `MENUS` (Sketch,
  Create, Modify, Construct, Inspect) and `TOOLS`, one `ExpertTool` per tool:
  key, menu, label, tooltip, window method, optional shortcut. The window builds
  one menu item per entry. `_apply_expert_mode` is the only code that shows or
  hides them: hidden *and* disabled when off, so their shortcuts do nothing, and
  a menu with no tools stays hidden even when on.
- **The toggle** is a checkable *Tools → Expert Mode* item. While on, the status
  bar shows "Expert mode". With it off, the menus, shelf, docks and bottom bar
  are exactly as before; the toggle is the one addition (tested against a
  snapshot of today's menus).
- **Turning it off changes no model.** Toggling takes no undo step and leaves
  the scene untouched. Shapes made with expert tools are ordinary shapes and
  stay visible and editable with the mode off.
- **Persistence lives in `run()`.** A `MeshWindow()` built without settings (as
  in the tests) starts from the defaults and saves nothing, so the test suite
  never reads or writes the user's real preferences.

## How the tools will fit the kernel (Phases 1–4, planned)

mesh works on closed triangle solids (manifold3d), not exact curved surfaces.
Each tool does the exact thing where the kernel allows it, and otherwise the
closest honest version, which its tooltip states and `docs/FOLLOWUPS.md` lists.

- **Reference objects.** Sketches, construction planes, axes and points are new
  hidden-from-shelf primitives marked as references. They are drawn and saved
  like any shape but never printed: Group, Join/Cut, the status bar check and
  Save for Printing skip them. With no reference objects in a scene, nothing
  behaves differently.
- **Sketches** hold 2D curves (line, rectangle, circle, arc, polygon, spline)
  in their own plane; the transform places that plane on the workplane, a
  construction plane, or a clicked flat face. There are no constraints (the
  binding spec rules them out): every curve is typed in millimetres, with a
  live 2D preview. Closed curves and chains of lines/arcs that meet end to end
  make the profile; a loop inside another is a hole in it.
- **Sketch-made solids** (Extrude, Revolve, Sweep, Loft) are new primitives
  that keep a copy of their profile in params, so distances and angles stay
  editable in the Details panel and the sketch can be edited again.
- **Modify tools** that change an existing part (fillet or chamfer an edge,
  push/pull a face, shell, split) return ordinary groups built from the part
  plus cutters or fillers, like Hollow out and Split, so Ungroup gives the
  original back.

## Phase 1 as built: sketches and Create

- **Modules.** `mesh/sketch.py` (curves, outlines, planes), `mesh/features.py`
  (the solids) and `mesh/create.py` (shapes made from sketches) are core and in
  the purity list. `mesh/sketch_editor.py` (the sketch window) and
  `mesh/expert_actions.py` (the menu handlers, mixed into `MeshWindow`) are GUI.
- **A sketch** is a shape with `params = {"primitive": "sketch", "entities":
  [...]}` and its plane as its transform. `shapes.REFERENCES` lists it apart
  from `PRIMITIVES`, so the shelf, the Details panel's size fields and the
  primitive tests are untouched. `shapes.is_reference` is what Group, Join,
  the status bar check, Save for Printing, Hollow out and Split use to leave
  it out or refuse it plainly.
- **Plane convention.** On an upright or sloping plane, sketch Y points up
  (the world's height, as seen from the side the plane faces) and X to the
  right; on a flat plane X follows the world's X. The origin is the point of
  the plane nearest the world origin, so typed numbers read like the Details
  panel's on the workplane and on flat faces.
- **Sketch-made parts** are new primitives (`extrude`, `revolve`, `sweep`,
  `loft`) holding a copy of their sketches' curves. Extrude's transform is its
  sketch's plane; Revolve's is the plane times `features.axis_frame(axis)`,
  so a fresh one stands upright; Sweep and Loft store each sketch's plane in
  params and use the world as their own coordinates. Making one is one undo
  step that also removes the sketches unless "Keep the sketch" is ticked.
  Change Sketch redraws the outline of an extrusion, revolve or sweep (the
  part must still come out solid, at its fit if it is a Hole); a revolve
  made around one of its sketch's lines (`axis_line`) follows that line; a
  loft is not redrawn.
- **Fits.** A Sweep or Loft grown by a fit's clearance can fail to build, so
  `create.fit_refusal` is checked before any change that rebuilds a Hole at
  a new fit (the Details panel, Make Hole, the fit sizes, Ungroup, Change
  Sketch), and the change is refused with the reason.
- **Results** are a new part or a Hole; joining and cutting stay with
  Solid/Hole + Group, as everywhere else in mesh.

## Project files

No new top-level fields and no `format_version` change are planned. New shape
types store their data (for example a sketch's curves) inside `params`, as
PR #1's rounded box and text do. Older builds can't open files that use them.
Phase 5 (named parameters, an editable history, components) would need new
project-file fields and is not started without asking first.
