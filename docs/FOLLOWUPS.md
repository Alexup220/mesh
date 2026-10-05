# mesh — known follow-ups

Triaged at the end of the initial build (2026-09-10, branch `build-mesh`). Nothing
here blocks use: the app builds, runs, and passes 187 tests. These are the things a
final whole-branch review and real hands-on use surfaced and deliberately deferred.

## Worth doing before this feels finished

- **Gizmo has no dedicated height handle.** The spec's "shapes never float by
  accident" idea is only half enforced. New shapes are placed on the workplane
  correctly, but `vtkBoxWidget2`'s face handles translate freely in Z, so a beginner
  can still drag a part into mid-air without meaning to. `ops.drop_to_plane` exists,
  is tested, and is not wired to anything — wiring it to a button is the cheap half
  of the fix; a dedicated elevation handle is the real one.
- **Empty-state inspector shows every size field at once.** With nothing selected the
  panel lists Width, Depth, Height, Diameter, Thickness and Wall thickness together,
  all reading 0.10. It is disabled so it is not interactive, but it should hide size
  fields entirely when there is no shape.
- **Selection rendering swamps tessellated shapes.** Selection uses per-facet edge
  display in yellow. On a 64-segment cylinder, sphere or torus the edges cover the
  surface, so a selected cylinder reads as a solid yellow blob rather than a shape
  with an outline. A silhouette outline or a highlight colour shift would read better.
- **No icons anywhere.** The bottom bar and shape shelf are text-only, and
  `mesh/resources/` does not exist. Deliberately skipped — icons need art.
- **No first-run tutorial overlay.** Deliberately skipped: worth writing only after
  watching someone actually get stuck.

## Correctness risks worth closing

- **The printcheck revision cache depends on an unenforced convention.** Caching
  `printcheck.check()` against a scene revision is only correct while every mutation
  bumps the revision by snapshotting first. That holds today across all mutation
  paths, including the gizmo drag, but nothing enforces it — a future mutation added
  without a snapshot would silently show stale printability. Consider asserting it.
- **Gizmo scale-baking is untested for rotation and scale composed together.** The
  decomposition math generalises correctly, but every test uses an unrotated
  transform. Add the composed case.
- **`Shape.from_dict` stores `params` by reference.** Not reachable today, since
  `load_project`'s parsed dict is function-local and snapshots deep-copy the scene.
  `dict(d["params"])` closes it permanently.
- **`trimesh.Scene.dump()` default could flip on upgrade.** Body splitting on import
  relies on it returning a list (`concatenate=False`). Worth a comment and a
  `trimesh<6` pin.
- **Group and imported shapes report position 0.** Their geometry is world-space
  baked, so the transform's translation stays 0 wherever they sit, and the inspector
  shows "Left / right (mm) = 0.00" for a group sitting at x=50. Primitives do not
  behave this way, so it reads as a bug rather than a convention.

## Test coverage gaps

- The tube's inner-radius clamp (`wall >= diameter/2`) is unexercised.
- `test_mirror_flips_an_asymmetric_shape` asserts only that the centre moved, which
  several wrong matrix orders would also satisfy.
- `test_duplicate_does_not_alias_the_original_params` mutates a dict key only; a
  shallow `dict.copy()` would pass it. Nothing stresses transform-array independence.
- The camera preset tests assert nothing about camera state, only that no exception
  is raised.
- No test covers real rendering — the suite runs under Qt's `offscreen` platform and
  skips `Render()` entirely. This is why a completely black viewport shipped through
  ten green task reviews and was only caught by launching the app and screenshotting
  it. Any future change to `mesh/viewport.py` needs a visual check, not just a suite.

## Expert mode, Phase 1 (sketches and Create): approximations and limits

mesh works on closed triangle solids, not exact curved surfaces, so these
tools do the closest honest version of their Fusion counterparts:

- **Curves are straight pieces.** A circle or arc is 64 pieces per whole turn
  (like a cylinder), a spline 16 pieces between typed points. Revolve's round
  surfaces are 64 flat strips per turn, Sweep follows a curved path in those
  same short straight steps, and Loft's smooth sides are 16 flat strips
  between one outline and the next.
- **No constraints or driving dimensions** between curves (the binding spec
  leaves them out): every curve is placed by its own typed numbers.
- **The sketch window** zooms with the mouse wheel, around the pointer, but
  does not pan; the drawing grows to show curves added out of sight and never
  shrinks back. Its number boxes take 3 decimals; a number left as it was in
  a curve's form keeps its exact value.
- **Sketches are not dragged.** A flat sketch's handle box would have no
  thickness, so the drag handles are hidden for sketches; they are moved and
  turned with the Details panel.
- **Extrude** goes "up to" a construction plane selected with the sketch
  only when the plane is parallel to the sketch (Fusion also ends on a face,
  a part, a point or a slanted plane). The distance is worked out once and
  kept as a number: moving the plane later leaves the end where it was,
  until the History is worked out again. Its sides slope by one angle (typed
  in the form, or later with Slope the Sides), which "Both ways" uses on
  both halves; Fusion can slope the two halves differently. Joined to, cut
  out of or kept where it overlaps a part works with one part selected with
  the sketch (Fusion takes several), and the result is a group, as Combine
  makes: Ungroup gives the part and the extrusion back. Its direction starts
  at "The way the sketch faces" for a cut or a hole too; the form says to
  choose "The other way" for a hole into a face sketched on.
- **Sweep** has no guide rails. Its twist and its size at the far end
  change evenly with the distance along the path, turning and scaling the
  outline about the path (Fusion can also scale about other points); on a
  closed path the twist must be whole turns and the size can't change. A
  twisted outline's straight pieces become narrow flat strips, about as fine
  as a cylinder's, so a twisted part is up to about 0.5% smaller than the
  true shape. A fitted Hole that changes size keeps the gap square to each
  straight piece of the outline, so its corners stay sharp rather than
  rounded. An outline drawn across
  either end of an open path, or anywhere round a closed one, is used where it
  is. Any other outline is moved to the nearer end (its middle onto the path),
  so an outline deliberately drawn beside the path is not swept at a distance.
  A path that crosses itself is refused, but one that only passes closer to
  itself than the outline's size is not caught, and makes a part that overlaps
  itself. Change Sketch redraws a sweep's outline, not its path.
- **Loft**: each sketch must hold one closed outline with no holes; no
  rails. A construction point picked first or last closes the loft to that
  point (a sketch point can't be used); where the point is is kept as
  numbers when the loft is made, so moving the point later leaves the tip
  where it was, until the History is worked out again. The point can't lie
  on the plane of the outline next to it. A loft's outlines can't be
  redrawn after it is made (undo, change the sketches, loft again). Its
  sides run straight
  from one outline to the next, or, as a choice, along a smooth curve through
  all of them: each matched point of the outlines follows a natural spline
  (the curve a sketch's spline uses), spaced by the distance between the
  outlines' middles. Fusion's smooth loft also lets you set how the sides
  leave the end outlines; here they leave them as the spline does. Sides
  that would pass through each other are refused by checking seven
  in-between outlines per strip, so a very brief crossing near an outline
  could slip through. A fitted Hole loft grows each outline in its own plane
  by more where the sides slope, so the gap square to the sides is at least
  the fit's clearance; it is larger than that on the gentler sides, and on
  sides almost flat (growth is capped at three times the clearance) it is
  less. With smooth sides the slope is the steepest anywhere between the
  outline before and the one after, and the sides in between follow the
  grown outlines, so their gap is about the clearance or more, not exactly
  at least it. A point the loft closes to moves out along the sides, far
  enough for the flat sides meeting there (also capped at three times the
  clearance, so a sharp tip's gap is less). Growing it exactly in 3D took 5
  to 10 seconds for curved outlines, too slow to redraw.
- **Size handles** do nothing on a part made from a sketch (they spring
  back): its size comes from the sketch and the Details panel numbers. Moving
  and turning it by its handles work as for any part.
- **Fits**: a Hole made by Sweep or Loft can be too big at a fit (a bend too
  tight, a gap closed up). Choosing such a fit, making it a hole at that fit,
  changing the fit sizes, or ungrouping it after they changed is refused with
  the reason, before anything changes.
- **Pre-existing: drag handles can linger.** Putting the handles away (for
  example after Select All or Delete from the keyboard) does not redraw the
  3D view, so the old handles stay drawn until the next redraw. Found during
  the Phase 1 check and fixed for sketches only, so the app with Expert mode
  off is unchanged; a one-line `_render()` in `Gizmo.attach` fixes the rest.

## Expert mode, Phase 2 (Modify): approximations and limits

- **Scale** changes size numbers, so a scaled primitive stays editable; the
  same amount in every direction is exact for every kind. Different amounts
  are exact only along a part's own sizes: a part turned by anything but
  quarter turns, a round part stretched unevenly across, a sphere, ring,
  revolve, sweep or loft stretched at all, and a sketch stretched unevenly
  are refused (Group first: a group stretches any way, in its transform, as
  its drag handles do). A rounding radius or bottom chamfer keeps its size
  when the directions differ. Hardware holes keep their standard sizes and
  move with the parts, their openings to where they were scaled to.
  Pre-existing: a stretched group's parts, once ungrouped, carry the stretch
  in their transforms, so a primitive's Details numbers show its size before
  the stretch (the same happens after dragging a group's handles today).
- **Shell** leaves open the flat face clicked, the one across from it if
  asked, and any more faces clicked on the same part (picked faces are
  drawn; Shell is chosen again to hollow it out). The walls go inside the
  part (its outside keeps its shape), outside it (its inside keeps its
  shape, and the walls stop level with each open face) or half each side.
  Boxes and cylinders (with no bottom chamfer) are exact through their flat
  sides and ends. Anything else is shelled approximately, the same way as
  Hollow out: the room inside keeps a 24-sided ball's distance from the
  outside, so walls can come out a little thinner in places; walls outside
  are grown with the same ball, so their outside corners come out rounded
  (Fusion keeps them sharp), and they are cut off level with an open face as
  far as three walls from its edge, so beside a side curving gently away
  from that face a low ridge can be left. A detailed part can take a few
  seconds (several with walls on both sides). A round surface is narrow
  flat strips, so clicking one opens just that strip, and only with a wall
  thinner than the strip is wide.
- **Push/Pull** moves the clicked flat face straight out or in, square to
  itself: the face's outline is pushed out as a new piece, or pushed in as a
  Hole. That is exact where the sides next to the face are square to it.
  Unlike Fusion, sloping sides next to the face are not extended along their
  slope, and a round surface can't be pushed as a whole: it is narrow flat
  strips, and only the strip clicked moves.
- **Round an Edge (Fillet)** rounds runs of edges: a run is the edge next
  to a click and the edges it runs on into smoothly (turning less than 30
  degrees), such as a cylinder's whole rim. One go can round the run
  clicked, every run round the face clicked, or the runs of more clicks on
  the same part (picked edges are drawn; the tool is chosen again to round
  them). It is exact for a straight edge between flat faces, with the round
  made of 16 straight pieces per quarter turn, as a circle has. Round
  surfaces are narrow flat strips, and the round follows them. Where
  rounded edges meet at a corner, the corner is not blended into a ball:
  rounded in one go, each run's round reaches the corner square to its
  edge, so two rounds meet in a crease and three come to a point. Rounding
  the next edge of a box after one is rounded, in a later go, follows the
  first round down the side; at a radius as big as the first one's it is
  refused ("too big for how tightly this edge bends"). A radius that would
  run off the faces next to the edge is refused with the largest that fits.
  Variable radius and setback corners are not offered, and edges are picked
  only by clicking a face beside them.
- **Bevel an Edge (Chamfer)** works the same way and has the same limits, with
  the edge cut flat: set back the same distance on both faces, a different
  distance on each (the first along the face clicked), or a distance along
  the face clicked and an angle from it. Exact for a straight edge between
  flat faces; along a curved run the second set back is worked out at each
  point from the faces' angle there.
- **Slope the Sides (Draft)** slopes every side of an Extrusion by one angle
  (at most 60 degrees), going away from its sketch's plane; a box, cylinder
  or tube becomes an Extrusion first (its base's outline pushed up its
  height), so a bottom chamfer is refused. Fusion's Draft slopes chosen faces
  from any plane; here all the sides slope together from the sketch, and
  other parts (a wedge, a group, a part with a pushed face) can't be sloped:
  sketch the outline and extrude it instead. Each straight side moves in
  keeping its direction, so corners stay sharp and a round outline slopes as
  its many narrow flat sides. A sloped fitted Hole grows square to its sides
  with sharp corners (a straight one's corners are rounded). Stretching a
  sloped Extrusion up or across changes its angle so its sides stay flat.

## Expert mode, Phase 3 (Patterns and Mirror): approximations and limits

The copies themselves are exact: each is the same part moved, turned or
reflected. What differs from Fusion is how the pattern is chosen.

- **Directions.** Pattern in Rows goes along left/right, forward/back,
  up/down or a construction axis selected with the parts, and Pattern
  Around a Line turns round a line along one of those three, through a
  point typed in millimetres, or round a construction axis selected with
  the parts (Phase 4). Fusion also lets an edge or a sloping face set the
  direction; picking one is not offered (make an axis through two points
  on the edge first).
- **Copies are left out by number**, typed (the parts are 1), where Fusion
  ticks them off in the view. Both ways (Fusion's symmetric) and spacing by
  the whole length are offered in Rows, and both ways in Around a Line; in
  both, the count and the spacing or angle go each way from the parts (so
  Around a Line's angle each way is less than 180 degrees). Along a Path
  goes one way only, and its spacing is from one copy to the next or spread
  over the whole path. Rows' two directions share one choice of spacing
  and of both ways.
- **Pattern Along a Path** needs a sketch as the path; a part's edge can't
  be picked. Curves are followed in their straight pieces (64 per circle),
  so a copy sits on a piece, slightly inside the true curve. With "Turn the
  copies as the path turns", the turn is blended across pieces that meet
  at less than 10 degrees (a curve) and jumps at sharper corners; copies
  turn only within the sketch's plane, never tilt out of it.
- **Copies are separate parts**, as Duplicate makes, not one feature.
  Changing the original later does not change the copies, and patterned
  Holes cut once grouped with the part, like any Hole.
- **Mirror** makes copies, or joins each image to its part into one part
  as Combine's Join does (a group, so Ungroup takes them apart; an image
  that doesn't touch its part is still joined into the same part, where
  Fusion would keep two bodies). The plane is a selected sketch's plane or
  construction plane, a clicked flat face, or one of the three middle
  planes through 0.

## Expert mode, Phase 4 (Construct and Inspect): approximations and limits

- **Guides follow what they were made from only through the history.** A
  construction plane, axis or point is placed by the numbers worked out
  when it is made, with no live link (Fusion keeps them linked). When the
  project keeps a history (Modify > History), a guide made by a Construct
  tool is made again whenever the history is worked out again (a step
  changed or removed, or new parameter values), so it follows what earlier
  steps did to the face, part, sketch or guide it came from. A change made
  after the guide (a later step, a drag, a number typed in the Details
  panel) does not move it, and a plane or axis through clicked points (or
  selected points) stays where those points were. Without a history,
  move or turn a guide in the Details panel, or make it again.
- **Construction planes** are drawn as a square (60 mm across, or sized
  round the face they came from) but go on without end. Offered: a plane a
  distance from a flat face, a sketch, another plane or the workplane's
  three planes; at an angle around the left/right, forward/back or upright
  line through 0; halfway between two faces (or two planes); and through
  three clicked points, where a click within 2 mm of a corner of the
  clicked face lands on the corner; and touching a round part where it is
  clicked. The touching plane is worked out from the part's own sizes (a
  cylinder, cone, tube, ring, ball, round hardware hole or revolved part,
  and a thread's crest and plain part), so it touches the true round
  surface rather than the flat strip clicked; a revolve's outline is
  itself made of short straight pieces, so on a curve in it the plane
  touches the piece clicked. A part made round another way (an Extrusion
  of a circle, a group, an imported part) can't be used. A plane along a
  path is square to the one path a selected sketch draws, a typed distance
  along it from either end; curves in the path are short straight pieces,
  and the plane's facing turns smoothly between pieces that meet at less
  than 10 degrees (at a sharper corner it is square to the piece after
  the corner). Fusion's distance as a fraction of the path's length is not
  offered; only millimetres.
- **Construction axes** are drawn as a line (120 mm, or longer for a long
  part) with an arrow showing the way it points, but go on without end.
  Offered: along the middle of a round part (a cylinder, cone, tube, ring,
  ball, round hardware hole or revolved part, read from its own numbers, so
  an Extrusion of a circle doesn't count); through two clicked points;
  square to a flat face at a clicked point; where two planes meet; and
  along a clicked edge. The edge is found as Round an Edge finds it (the
  sharp edge of the clicked face nearest the click), and the axis runs
  along the straight stretch of it clicked; a round edge is short straight
  pieces, so there it runs along the one piece clicked. Pattern Around a Line
  and Plane at an Angle turn around a selected axis; Revolve still turns
  around a line in its sketch.
- **Construction points** are drawn as a small cross. Offered: at a click
  on a part (on the face's corner within 2 mm of it), at the middle of a
  flat face's area (a cylinder's end gives its centre), and at the end of
  a clicked edge nearer the click (the end of the straight stretch
  clicked, so on a round edge an end of the short piece clicked); where
  three selected sketches or planes meet; and where a selected axis meets
  a selected sketch or plane. Fusion's point where a part's edge meets a
  face is not offered. Three selected points make a plane and two make an
  axis; nothing else takes a point yet.
- **Section view** only changes the view, one plane at a time, and is
  not saved with the project (Fusion keeps section analyses in the
  browser). The plane is a selected sketch or construction plane, or a
  flat or upright plane through the middle of the parts, moved by a typed
  distance. The orange cut faces can't be clicked as a part's face; a
  click there counts as a click on nothing. A part with gaps can't be
  closed, so it is cut along its triangles with no cap.
- **Measure Between Faces** measures between two clicked points on flat
  faces (within 2 mm of a corner, from the corner). A click on a round
  surface lands on one of its narrow flat strips, so the "face area" is
  that strip's and the angle is the strip's. The angle is between the
  faces' planes (0 to 90 degrees).
- **Length of an Edge** measures the edge next to a click, found as Round
  an Edge finds it, on the part as drawn: a round edge is short straight
  pieces, so its length comes out a little short of the true curve, and
  the straight stretch clicked is one of those pieces. Edges are found
  only on parts of up to 50,000 triangles.
- **Radius of a Round Face** reads the radius from the part's own sizes
  (a cylinder, cone, tube, ring, ball, round hardware hole, a thread's
  crest or a revolved part's outline, a Hole at its fit), so it is the
  true radius, not the flat strips'. A cone gives both ends and the
  radius where clicked; a ring or rounded edge gives both ways it curves.
  A revolved part's curved outline is short straight pieces, so there it
  is the one piece clicked. Any other part (a box, an imported part, one
  a Modify tool has changed) or a part stretched unevenly says its radius
  can't be told; Fusion measures any round face.
- **Shortest Distance Between Parts** measures two selected parts as they
  are drawn (a Hole at its fit), so next to a round surface, made of flat
  strips, it can be slightly off the true distance. It gives the distance
  only: the two nearest points are not shown, and parts that touch or
  overlap are said to (Fusion draws the nearest points). A part with gaps
  in its surface can't be measured.
- **Volume and Area** measures the selected parts as they would print
  together (overlaps once, selected Holes cut out). Fusion's mass and
  centre of gravity are not offered.
- **Thread** goes on a plain cylinder only (Fusion threads any round
  face): a threaded hole is a cylinder Hole with a thread, grouped with
  the part. Only the ISO metric shape is offered (no inch, pipe, tapered
  or several-start threads), always modeled, never just drawn on. The
  sloped sides are narrow flat strips, 36 to a turn, so the thread is
  about 0.5% thinner than the true shape. A fitted thread Hole grows by
  its fit straight out from the middle, which leaves about half the fit
  as room on the sloped sides. The ends are cut square, with no lead-in
  bevel, and a thread makes at most 150 turns.

## Expert mode, Phase 5 (Parameters, History, Components): approximations and limits

- **Parameters** link a part's position, turn and its own size numbers
  (width, height, radius and so on) to formulas. While the project keeps
  a history, a tool's settings (an extrusion's distance, a rounding's
  radius, a pattern's count) can use them too (History > Use
  Parameters); a count is rounded to a whole number. A sketch's curves
  can be linked (each number of each curve, numbered as Change Sketch
  lists them), and so can the curves a part made from a sketch keeps;
  the part follows its own linked curves at once, and its sketch's only
  while a history is kept (the tool runs again). A sweep's path and a
  loft's outlines can't be linked, nor can text, hardware sizes or
  imported parts, and a tool's settings can't use a parameter when no
  history is kept; Fusion lets any dimension or feature number use a
  parameter. Units are always
  millimetres and degrees (Fusion lets a parameter carry its own unit).
  A turn read back from a part is worked out from the part's turned
  position, so a linked turn keeps the other two turns as they come out
  of that working (the same numbers the Details panel shows).
- **History** starts when you ask (Modify > History > Start Keeping a
  History) and lists the changes from then on; it can't recover what
  happened before. Steps can be changed, skipped (and used again), moved
  earlier or later, or removed. There is no timeline marker to roll the
  project back to a step and add new steps there (Fusion's): skip the
  later steps, or Undo, instead. A step can't move before the step that
  makes a part it uses.
  A step's settings can be changed (an extrusion's distance, a
  rounding's radius, a pattern's count), and so can the curves of a step
  that drew a sketch or changed one (Change... opens the sketch window),
  so parts made from it later follow. A tool used on the selected parts
  can be used on other parts instead (select them, then Use on
  Selection); one used on a clicked face (Round an Edge, Shell ...) or on
  a part it names can't be moved to other parts. Steps that are not
  tools (adding a shape, moving or dragging, typing in the Details panel,
  drawing a sketch, Lay Flat, Align Face to Face) do again what they did:
  a move moves the part by the same amount from wherever it is by then,
  and a typed size is set again as typed. A clicked face is found again
  by the way it faces and where it was, so a change that turns or
  reshapes a part a lot can make a later tool land on a different face,
  or refuse. The whole project is worked out again after every change,
  which can take a while on a long history.
- **Components** keep separate parts together under a name, and can hold
  other components, as Fusion's do. They have no origin or joints of
  their own (Fusion's Assemble joints and motion are not offered), and a
  copy is independent: changing one copy does not change the others
  (Fusion's linked copies do). A part made by a tool from parts
  of one component joins it; from parts of two different components, it
  joins neither. A hidden component stays hidden with Expert mode off,
  until Expert mode is turned on again to show it.

## Platform notes

- The app forces Qt's `xcb` platform (XWayland) in `mesh/app.py:run`, because VTK's
  Linux OpenGL backend is X11-only and fails with BadWindow under native Wayland.
- `mesh/viewport.py` must import `vtkmodules.vtkRenderingOpenGL2`. Without it,
  `vtkRenderWindow()` silently instantiates the abstract base class and paints
  nothing at all — no error, just a black viewport.
