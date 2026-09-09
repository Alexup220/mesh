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

## Platform notes

- The app forces Qt's `xcb` platform (XWayland) in `mesh/app.py:run`, because VTK's
  Linux OpenGL backend is X11-only and fails with BadWindow under native Wayland.
- `mesh/viewport.py` must import `vtkmodules.vtkRenderingOpenGL2`. Without it,
  `vtkRenderWindow()` silently instantiates the abstract base class and paints
  nothing at all — no error, just a black viewport.
