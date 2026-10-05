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
- **Shell** leaves one clicked flat face open, or that face and the one
  across from it; Fusion's free choice of any number of faces, and walls
  grown outward instead of inward, are not offered. Boxes and cylinders (with
  no bottom chamfer) are exact through their flat sides and ends. Anything
  else is shelled approximately, the same way as Hollow out: the room inside
  keeps a 24-sided ball's distance from the outside, so walls can come out a
  little thinner in places, and a detailed part can take a few seconds. A
  round surface is narrow flat strips, so clicking one opens just that strip,
  and only with a wall thinner than the strip is wide.
- **Push/Pull** moves the clicked flat face straight out or in, square to
  itself: the face's outline is pushed out as a new piece, or pushed in as a
  Hole. That is exact where the sides next to the face are square to it.
  Unlike Fusion, sloping sides next to the face are not extended along their
  slope, and a round surface can't be pushed as a whole: it is narrow flat
  strips, and only the strip clicked moves.
- **Round an Edge (Fillet)** rounds one run of edges per click: the edge
  next to the click and the edges it runs on into smoothly (turning less than
  30 degrees), such as a cylinder's whole rim. Picking several separate edges
  at once is not offered. It is exact for a straight edge between flat faces,
  with the round made of 16 straight pieces per quarter turn, as a circle has.
  Round surfaces are narrow flat strips, and the round follows them. Where
  rounded edges meet at a corner, the corner is not blended into a ball, and
  rounding the next edge of a box after one is rounded follows the first
  round down the side; at a radius as big as the first one's it is refused
  ("too big for how tightly this edge bends"), where Fusion would blend the
  corner. A radius that would run off the faces next to the edge is refused
  with the largest that fits. Variable radius and setback corners are not
  offered.
- **Bevel an Edge (Chamfer)** works the same way and has the same limits, with
  the edge cut flat, set back the same distance on both faces. A bevel set
  back a different distance on each face, or given by an angle, is not
  offered.
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

- **Directions are the world's.** Pattern in Rows goes along left/right,
  forward/back or up/down, and Pattern Around a Line turns round a line
  along one of those three, through a point typed in millimetres, or round
  a construction axis selected with the parts (Phase 4). Fusion also lets
  an edge or a sloping face set the direction; picking one is not offered.
- **No suppressing single copies**, no "symmetric" (both ways from the
  part) option, and no spacing by total extent in Rows: spacing is from one
  copy to the next.
- **Pattern Along a Path** needs a sketch as the path; a part's edge can't
  be picked. Curves are followed in their straight pieces (64 per circle),
  so a copy sits on a piece, slightly inside the true curve. With "Turn the
  copies as the path turns", the turn is blended across pieces that meet
  at less than 10 degrees (a curve) and jumps at sharper corners; copies
  turn only within the sketch's plane, never tilt out of it.
- **Copies are separate parts**, as Duplicate makes, not one feature.
  Changing the original later does not change the copies, and patterned
  Holes cut once grouped with the part, like any Hole.
- **Mirror makes copies only.** Fusion can also mirror a part into one
  joined body; here Combine (Join) joins a copy to its part. The plane is a
  selected sketch's plane or construction plane, a clicked flat face, or one
  of the three middle planes through 0.

## Expert mode, Phase 4 (Construct and Inspect): approximations and limits

- **Guides don't follow what they were made from.** A construction plane,
  axis or point is placed by the numbers worked out when it is made;
  moving the part or sketch afterwards leaves the guide where it was
  (Fusion keeps them linked). Move or turn it in the Details panel, or
  make it again.
- **Construction planes** are drawn as a square (60 mm across, or sized
  round the face they came from) but go on without end. Offered: a plane a
  distance from a flat face, a sketch, another plane or the workplane's
  three planes; at an angle around the left/right, forward/back or upright
  line through 0; halfway between two faces (or two planes); and through
  three clicked points, where a click within 2 mm of a corner of the
  clicked face lands on the corner. Fusion's plane touching a round surface
  and plane along a path are not offered.
- **Construction axes** are drawn as a line (120 mm, or longer for a long
  part) with an arrow showing the way it points, but go on without end.
  Offered: along the middle of a round part (a cylinder, cone, tube, ring,
  ball, round hardware hole or revolved part, read from its own numbers, so
  an Extrusion of a circle doesn't count); through two clicked points;
  square to a flat face at a clicked point; and where two planes meet.
  Fusion's axis along a clicked edge is not offered. Pattern Around a Line
  and Plane at an Angle turn around a selected axis; Revolve still turns
  around a line in its sketch.
- **Construction points** are drawn as a small cross. Offered: at a click
  on a part (on the face's corner within 2 mm of it) and at the middle of a
  flat face's area (a cylinder's end gives its centre). Fusion's point at
  the end of an edge, where an edge meets a face, or where three planes
  meet is not offered. Three selected points make a plane and two make an
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
  faces' planes (0 to 90 degrees). Fusion's measuring of edges, of a round
  face's radius and of the shortest distance between two parts is not
  offered.
- **Volume and Area** measures the selected parts as they would print
  together (overlaps once, selected Holes cut out). Fusion's mass and
  centre of gravity are not offered.
- **Thread** goes on a plain cylinder only (Fusion threads any round
  face): a threaded hole is a cylinder Hole with a thread, grouped with
  the part, and a threaded tube is a threaded cylinder grouped with a
  cylinder Hole through it (selecting a tube says so). Metric (ISO), inch (UNC, which has the same 60 degree shape)
  and straight British pipe threads (G, ISO 228-1, the 55 degree shape
  with round tips) are offered, always modeled, never just drawn on.
  Tapered pipe threads (NPT, R) are not, and only the coarse inch sizes
  are listed (a fine pitch, or any threads per inch, can be typed). The
  cylinder keeps its own diameter: the standard sizes only fill in the
  pitch for the size nearest it. One to four threads can run side by
  side (several starts); the pitch stays the distance from one ridge to
  the next. The sloped sides are narrow flat strips, 36 to a turn for
  each start, and a pipe thread's round tips are short flat pieces (6 to
  each half), so the thread is about 0.5% thinner than the true shape. A
  fitted thread Hole grows by its fit straight out from the middle, which
  leaves about half the fit as room on the sloped sides. The end where the
  thread starts can be bevelled at 45 degrees (a thread down to its root,
  a threaded hole out to its full size), as a cone of flat strips; the
  bevel's angle and size can't be chosen, and the far end is always cut
  square. A thread makes at most 150 turns, counting each start.
- **Coil** (Create menu) makes a spring of round or square wire, set by
  its outside diameter, pitch, number of turns and wire thickness. The
  wire's outline is drawn in the upright plane through the middle line,
  as Fusion draws a coil's section, and carried round it, so the ends are
  cut square across the wire there. Fusion's flat spiral, its triangle
  wire, a tapering coil and placing the wire inside or outside the
  diameter are not offered. Each turn is 48 straight pieces and a round
  wire has 24 sides, so the coil is about 0.3% thinner than a true one.
  The turns can't touch (the pitch must be more than the wire, and more
  than the wire plus twice the fit for a fitted Hole), and a coil scales
  only alike in every direction.

## Expert mode, Phase 5 (Parameters, History, Components): approximations and limits

- **Parameters** link a part's position, turn and its own size numbers
  (width, height, radius and so on) to formulas. Sketch curves, text,
  hardware sizes, imported parts and the numbers inside a recorded tool
  (an extrude's distance, a fillet's radius) can't be linked; Fusion lets
  any dimension or feature number use a parameter. Units are always
  millimetres and degrees (Fusion lets a parameter carry its own unit).
  A turn read back from a part is worked out from the part's turned
  position, so a linked turn keeps the other two turns as they come out
  of that working (the same numbers the Details panel shows).
- **History** starts when you ask (Modify > History > Start Keeping a
  History) and lists the changes from then on; it can't recover what
  happened before. Steps can be changed or removed but not reordered or
  rolled back to (Fusion's timeline marker); Undo goes back instead.
  Only the tools' own settings can be changed (an extrusion's distance, a
  rounding's radius, a pattern's count); which parts a tool was used on,
  and a sketch's curves, can't be changed in a step. Steps that are not
  tools (adding a shape, moving or dragging, typing in the Details panel,
  drawing a sketch, Lay Flat, Align Face to Face) do again what they did:
  a move moves the part by the same amount from wherever it is by then,
  and a typed size is set again as typed. A clicked face is found again
  by the way it faces and where it was, so a change that turns or
  reshapes a part a lot can make a later tool land on a different face,
  or refuse. The whole project is worked out again after every change,
  which can take a while on a long history.
- **Components** keep separate parts together under a name. They don't
  hold other components (Fusion's components nest), have no origin or
  joints of their own (Fusion's Assemble joints and motion are not
  offered), and a copy is independent: changing one copy does not change
  the others (Fusion's linked copies do). A part made by a tool from parts
  of one component joins it; from parts of two different components, it
  joins neither. A hidden component stays hidden with Expert mode off,
  until Expert mode is turned on again to show it.

## Platform notes

- The app forces Qt's `xcb` platform (XWayland) in `mesh/app.py:run`, because VTK's
  Linux OpenGL backend is X11-only and fails with BadWindow under native Wayland.
- `mesh/viewport.py` must import `vtkmodules.vtkRenderingOpenGL2`. Without it,
  `vtkRenderWindow()` silently instantiates the abstract base class and paints
  nothing at all — no error, just a black viewport.
