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

## Phase 5 as built: parameters, history, components

- **Modules.** `mesh/parameters.py` (formulas and links),
  `mesh/history.py` (steps, what a step changed, finding a clicked face
  again) and `mesh/components.py` are core, in the purity list. The window
  side is `ParameterActions`, `HistoryActions` and `ComponentActions`
  (`mesh/parameter_actions.py`, `mesh/history_actions.py`,
  `mesh/component_actions.py`), mixed into `ExpertActions`. Components
  have their own Assemble menu.
- **Parameters** are a table on the scene (`Scene.parameters`: name,
  formula, note). A part's links (`Shape.links`, field to formula) set its
  position, turn or size numbers whenever the parameters change. Formulas
  are read by a small calculator built on Python's `ast`, never `eval`.
  Typing a number in the Details panel ends that number's link
  (`app._on_edited` calls `_end_link`). Every linked part is built on a
  copy first, so a parameter that would break one changes nothing.
- **History** is a list on the scene (`Scene.history`: the scene when it
  started, then the steps), so undo and saving carry it. `Document.snapshot`
  adds a step when the project keeps a history; `Document.settle` works
  out what the newest step changed (`history.changes`) by comparing the
  scene before it (the undo copy) with the scene now. Window methods
  marked `@replayable` (the tools) also record their call: settings, the
  selection in picked order and, for a clicked face, where it was and
  which way it faced. Changing or removing a step replays the whole list
  from the start on a scratch document: a tool step calls its method
  again (its new parts get back their recorded ids, so later steps find
  them; a clicked face is found again by `history.find_face`), other steps
  apply what they changed (a move as a move). The result replaces the
  project as one undo step that is not itself a history step. With a
  history kept, new parameter values replay it too, so tools downstream
  of a linked size follow (Fusion's parametric timeline).
- **Components** are a list on the scene (`Scene.components`: id, name),
  and each part names its component (`Shape.component`). Ids come from
  what a component was made from (`components.new_id`), so a replay gives
  the same ids. What a tool makes by replacing parts of one component
  joins it: the window's `sync` calls `components.carry_over` with the
  scene before the newest change (`Document.action_before`), and the
  replay does the same after each tool step.

## Closing the gaps (after Phase 5)

Every gap listed in `docs/FOLLOWUPS.md` that mesh can close with the
libraries it already has was closed, one commit each; what stays
approximate is still listed there and in each tool's tooltip. Curves stay
straight pieces, and sketches stay without constraints (both by the
user's choice).

- **History.** A step can be skipped (`"off": true` on the step; the
  replay passes over it and keeps it as it was), moved (the list is
  reordered and replayed; `history.made_later` turns a missing part that
  a later step makes into a plain reason), used on the parts selected now
  (its call's `picked` replaced; not for a step used on a clicked face or
  on a part it names), and a step that drew or changed a sketch's curves
  can be given new curves (its effect's `entities` replaced, then
  replayed, so parts later made from the sketch follow). A tool used on a
  clicked face no longer needs the rest of the selection it was recorded
  with.
- **Formulas in a step's settings.** `call["formulas"]` maps a field of
  the tool's own form (the `editors()` entry) to a formula. On every
  replay `_worked_call` fills the form's values from the step, puts in
  what the formulas come to (`history.formula_values`: a count rounded,
  each number inside the form field's limits) and turns them back into
  settings with the form's own `back`, so the mapping is the same as
  Change... uses. Typing a new number in Change... ends that formula.
- **Sketch curves as links.** `parameters.linkable` lists each number of
  each curve in a shape's `entities` ("curve2.width", "curve1.corner.x",
  "curve3.points.2.y"); setting one rebuilds that curve through
  `sketch.clean_entity`, so a link can never leave a curve a sketch can't
  draw. Change Sketch ends the links of numbers typed over or curves
  taken out (`parameters.links_kept`).
- **Components inside components.** A component may have a `"parent"`.
  `components.inside` gives a component and everything in it; select,
  show or hide, copy and save for printing work on that whole set, while a
  part's own `component` stays its direct one (so `carry_over` is
  unchanged). `components.read` drops a parent that is missing or loops.
- **Create.** Extrude takes its side slope in its form, can go up to a
  construction plane (the distance is worked out once, by
  `create.distance_to_plane`), and can join to, cut from or keep the
  overlap with a part selected with it (`modify.combine`, one step).
  Sweep has `twist` and `end_scale`. Loft has `sides` ("smooth": a smooth
  curve through three or more outlines) and a `{point}` section at either
  end. Thread has `starts` (1 to 4), `thread_shape` ("round": the 55
  degree Whitworth shape of British pipe threads; inch threads are the 60
  degree shape with the pitch 25.4 mm over the threads per inch) and
  `lead_in` ("bevel": a 45 degree cone at the starting end, which on a
  Hole becomes a countersink, so `primitive_mesh` now passes whether the
  shape is a Hole). Coil is a new primitive (`mesh/coils.py`, in the
  purity test's CORE list): its wire's outline in an upright plane through
  the middle line, extruded as a straight bar and bent round into the
  turns with manifold3d's `warp_batch`. Pipe is a new sketch solid in
  `features.SOLIDS`, a sweep of one circle (two for a hollow pipe).
- **Modify, patterns and Mirror.** Mirror can join each image to its part.
  Patterns go both ways, over a whole length, along a construction axis,
  and leave copies out by number; Pattern Along a Path can follow a
  clicked edge run. Bevel an Edge takes two distances or a distance and
  an angle, Round and Bevel take several edges in one go, Shell leaves
  several faces open with walls inside, outside or both, and Push/Pull can
  carry sloping sides on along their slope (`follow_sides`).
- **Construct and Inspect.** A plane touching a round part (worked out
  from the part's own sizes, `construct.round_spot`), a plane along a
  path, an axis along an edge, a point at an edge's end, and points where
  three planes or an axis and a plane meet. Inspect adds the shortest
  distance between parts (manifold3d's `min_gap`), a round face's radius,
  an edge's length, and the centre of gravity and weight (by a chosen
  material's density) in Volume and Area. The sketch window pans (right
  or middle drag) and fits the whole drawing.
- **Left as they are**, each with its reason in FOLLOWUPS: Draft on chosen
  faces (a part's sides are not kept as named faces, so a choice of sides
  could not be recorded to survive later changes), a thread on a tube (a
  threaded cylinder grouped with a cylinder Hole already makes it, with
  the Hole's fit), tapered pipe threads, joints, motion, linked copies,
  sketch constraints and true curved surfaces.

## Project files

Phases 0 to 4 add no top-level fields and no `format_version` change. New
shape types store their data (for example a sketch's curves) inside
`params`, as PR #1's rounded box and text do. Older builds can't open files
that use them.

Phase 5's data is saved only when used: `parameters`, `components` and
`history` in the scene, and `links` and `component` on a shape. A project
that uses any of them is saved as `format_version` 2
(`io_formats.format_version`); every other project is still saved as
version 1, exactly as before. Loading refuses a version above 2 with a
plain message (a newer mesh saved it), and old STL shape blobs still
decode.
