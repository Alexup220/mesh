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

## Phase 2 as built: Modify

- **Modules.** `mesh/modify.py` (Move or Copy, Align, Scale, Combine, Split
  Body, Shell, Push/Pull, Draft) and `mesh/edges.py` (Fillet and Chamfer) are
  core and in the purity list. `mesh/modify_actions.py` holds their forms and
  menu handlers in `ModifyActions`, the base of `ExpertActions`. Every core
  function returns new shapes or changed copies and raises `BuildError` with
  a plain message on refusal; the window snapshots only on success.
- **Click tools.** Align, Shell, Push/Pull, Fillet and Chamfer wait for a
  click on a part (`MODIFY_CLICK_TOOLS`); `EXPERT_CLICK_HANDLERS` routes the
  click (part, triangle, point) to each tool's handler. A click that can't be
  used keeps the tool waiting with the reason in the status bar. Forms open
  after the click is over (`QTimer.singleShot(0)`), so the view's drag ends.
- **Faces and edges.** A flat face is the facet holding the clicked triangle
  (`modify.flat_face`). An edge is where two faces meet at more than 20
  degrees; Fillet and Chamfer take the edge of the clicked face nearest the
  click and follow it on through corners that turn less than 30 degrees
  (`edges.find_run`).
- **Groups.** Combine, Split Body (each piece), Shell, Push/Pull, Fillet and
  Chamfer return ordinary groups of the part plus pieces added or cut away
  (Holes), so Ungroup gives the part back.
- **Sizes stay numbers.** Move or Copy and Align change the transform. Scale
  changes size params (primitives stay editable), or the transform for
  imported parts and groups. Draft is a `taper` param (degrees) on `extrude`,
  0 when missing: each straight side of the outline moves in by distance times
  tan(taper), keeping its direction (`features._tapered`); a box, cylinder or
  tube becomes an `extrude` first. Sides that would meet are refused, and a
  number typed in the Details panel for any part made from a sketch is
  test-built first (`create.edit_refusal`).

## Phase 3 as built: Patterns and Mirror

- **Modules.** `mesh/patterns.py` (core, in the purity list) makes the
  copies; `mesh/pattern_actions.py` holds the forms and handlers in
  `PatternActions`, mixed into `ExpertActions` beside `ModifyActions`. The
  four tools sit in the Create menu, after Loft.
- **Copies, not features.** Every tool returns new shapes made as Duplicate
  makes them (new ids, same params, Solid/Hole and fit), moved by one world
  matrix each, and the window adds them with the parts selected, as one
  undo step. Nothing links a copy to its original afterwards, and nothing
  new is saved: a copy is an ordinary shape.
- **Counts include the parts**, as Fusion's do. Rows go along the world's
  three directions; Around a Line turns round a line along one of them
  through a typed point (Repeat in a Circle stays as it was, for beginners).
- **Along a Path** uses the one path a selected sketch draws
  (`sketch.single_path`, as Sweep does), in the sketch's own plane: from the
  end nearest the parts, or round a closed path from its point nearest them.
  Each copy moves by the path's step from that start; "turn" adds the
  change in the path's direction, blended over pieces that meet at less than
  10 degrees so a circle's copies turn smoothly.
- **Mirror** reflects (`I - 2nnᵀ`), so a copy's transform turns inside out;
  the geometry is built from it with its faces the right way out, and the
  copy is named "(mirrored)". The plane is a selected sketch's (used at once,
  no form), a flat face clicked next (`mirror_face`, a click tool like
  Phase 2's), or a middle plane through 0.

## Phase 4 as built: Construct and Inspect

- **Modules.** `mesh/guides.py` draws the construction guides and
  `mesh/construct.py` works out where they go; `mesh/section.py` cuts the
  drawing for the section view, `mesh/measure.py` measures and
  `mesh/threads.py` builds threads (all core, in the purity list). The
  window side is `ConstructActions` (`mesh/construct_actions.py`) and
  `InspectActions` (`mesh/inspect_actions.py`), mixed into
  `ExpertActions`; Thread's form is with the other Create tools in
  `mesh/expert_actions.py`.
- **Guides are references.** `plane`, `axis` and `point` join `sketch` in
  `shapes.REFERENCES`, so they are shown and saved but never printed,
  grouped or combined. Each is only its transform (plus a drawn size); it
  does not follow the face or part it was made from. Other tools take
  them: New Sketch draws on a selected plane, Mirror and Split Body use a
  plane, Pattern Around a Line and Plane at an Angle turn round an axis,
  and three or two selected points make a plane or an axis at once.
  Multi-click tools show a prompt per click (`_STAGED`, read through the
  window's `_tool_prompt`).
- **Section view** is view state on the 3D view (`Viewport.section`), never
  in the scene: no undo step, not saved, cleared when Expert mode goes off
  or another project opens. Each part's drawing is trimmed with manifold3d
  (`trim_by_plane`) keeping a face id per triangle, so a click on a cut
  part maps back to the part's own face (`Viewport.face_of_cell`); the cap
  is a separate orange actor that counts as no part for click tools.
- **Measure Between Faces** is a click tool that stays on, like the
  beginner Measure, and shows its results in a window that stays open.
  **Volume and Area** measures `ops.evaluate` of the selection, the parts
  as they would print together. Neither changes anything.
- **Thread** turns a selected cylinder into a `thread` primitive (same id,
  place, colour, Solid/Hole and fit). It is one ISO 68-1 cross-section
  extruded with a twist of 360 degrees per pitch, 36 steps a turn; a
  left-hand thread is the right-hand one mirrored. A Hole's fit grows the
  radius and both ends but keeps the turns where they were, so a bolt of
  the same sizes fits inside it. Pitch, threaded length, end and hand are
  Details panel fields, checked through `create.edit_refusal`.

## Project files

No new top-level fields and no `format_version` change are planned. New shape
types store their data (for example a sketch's curves) inside `params`, as
PR #1's rounded box and text do. Older builds can't open files that use them.
Phase 5 (named parameters, an editable history, components) would need new
project-file fields and is not started without asking first.
