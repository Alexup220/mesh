# mesh

Easy 3D modeling for 3D printing.

Drop shapes on the workplane, mark the ones you want removed as **holes**,
press **Group**, and save a printable STL. Everything is in millimetres.

## Run

    ~/mesh/bin/mesh

## Install the launcher

    ln -sf ~/mesh/bin/mesh ~/.local/bin/mesh
    cp ~/mesh/mesh.desktop ~/.local/share/applications/

## Tools for real printed parts

Everything here is in millimetres, and everything can be undone with `Ctrl+Z`.

- **Fit (for holes).** Select a hole and pick a fit in the Details panel:
  *Exact*, *Press fit*, *Snug fit* or *Loose fit*. A fit adds a little room on
  every side of the hole so the part that goes in actually fits after printing:
  a 10 mm snug hole comes out 10.4 mm across. Change how much room each fit adds
  under **Shape → Fit clearances…** (Press 0.1, Snug 0.2, Loose 0.4 mm per side
  to start with). On a hole made from an added model file or a group, the fit
  stretches the hole evenly, which is close but not exact.
- **Add hardware hole.** Ready-made holes for screws (plain, countersunk or
  counterbored, M2–M6), hex nut traps (M2–M6), heat-set insert pockets (M2–M5)
  and magnet pockets (10×2, 8×2, 6×2, 4×2 mm). Each is one hole you can move and
  change; its size is a drop-down in the Details panel. The opening is at the
  top, so put it into a top face (or use *Place on a face*). Heat-set insert and
  counterbore sizes vary by brand: check them against your hardware.
- **Lay flat on a face** (`L`). Click a face of a part and it turns so that face
  sits on the workplane.
- **Place next shape on a face** (`P`). Click a face of a part, then add any
  shape: it lands on that face, lined up with it. Holes, hardware holes and
  engraved text are sunk into the face instead. Works once, then switches off.
- **Hollow out…** Turns a solid into a shell with the wall thickness you choose,
  with an optional open top and drain hole. Boxes, cylinders and spheres come
  out exact; other shapes are hollowed approximately, and the window says so.
- **Split part…** Cuts a part in two, flat or upright, at the distance you
  choose, and lays both halves out ready to print. Tick *Add alignment pegs* to
  get pegs on one half and snug holes on the other.
- **Rounded box** and **Rounded cylinder** on the shape shelf, with a
  *Rounding radius*.
- **Bottom chamfer.** Boxes, cylinders and the rounded shapes have a *Bottom
  chamfer (mm)* field. A small chamfer (0.4–0.6 mm) stops the first layer
  squashing out into a lip.
- **Repeat in a row… / Repeat in a circle…** Makes copies of the selected part
  in a line or around a circle, in one step. Copies of a hole stay holes.
- **Box with lid…** Makes a box and a lid that drops onto it, side by side.
- **Add text…** (`T`). Raised text stands up from the plane; engraved text is a
  hole, so place it on a face to cut words into a part. The font is built in.
- **Measure** (`M`). Click two points on parts to see the distance between them.

`Esc` stops whichever of the click-on-a-part tools is running.

## Expert mode

**Tools → Expert Mode** shows a larger set of modeling tools for people who
have modeled before, in extra menus between *Tools* and *View*. It is off on a
fresh install, and mesh looks exactly as described above until you turn it on.
The choice is remembered on this computer (in `~/.config/mesh/settings.json`),
never in a project file, so opening a project doesn't change it. Turning it
off only hides the tools: anything you made with them stays in your model,
visible and editable.

## Shortcuts

| Key | Action |
|---|---|
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / Ungroup |
| `Ctrl+D` | Duplicate |
| `Delete` | Delete |
| `H` | Toggle hole |
| `Ctrl+S` / `Ctrl+O` | Save / Open project |
| `Ctrl+E` | Save for printing |
| `Home` | Reset camera |
| `1` `3` `7` | Front / Right / Top |
| `F` | Zoom to selection |
| `L` | Lay flat on a face |
| `P` | Place next shape on a face |
| `T` | Add text |
| `M` | Measure |
| `Esc` | Stop the current tool |

## Develop

    uv sync
    uv run pytest

## Wayland note

The 3D viewport runs on VTK's `vtkXOpenGLRenderWindow`, which is X11-only:
it hands the viewport widget's native window id straight to X11 calls, and
under Qt's native `wayland` platform plugin that id isn't a real X11 window,
so VTK crashes on its first `XChangeWindowAttributes` call
(`X Error: BadWindow (invalid Window parameter)`). Because of that, `mesh`
defaults `QT_QPA_PLATFORM` to `xcb` (i.e. runs through XWayland) before
`QApplication` is created, unless it's already set in the environment. This
is why the 3D view works under Hyprland/Wayland today; it can be revisited
if a native-Wayland VTK backend becomes available for this Qt integration.
