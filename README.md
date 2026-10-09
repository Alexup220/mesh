# mesh

Easy 3D modeling for 3D printing.

Drop shapes on the workplane, mark the ones you want removed as **holes**,
press **Group**, and save a printable STL. Everything is in millimetres.

## Run

    ~/mesh/bin/mesh

`~/mesh/bin/mesh --classic` starts the original window instead. It has the
same tools; its *Details* panel is the *Properties* panel described below.

## The window

- **Top:** the menu bar, and the ribbon below it with four tabs: *Create*,
  *Modify*, *Inspect* and *Export*. Every button has an icon and a name;
  hover over it to see what it does and its shortcut. With Expert mode on,
  the ribbon and menus grow to hold the expert tools.
- **Left:** the *Tools* palette (the click-on-a-part tools and everyday
  edits) and the *Insert* panel. Click a thumbnail to add that shape to
  the middle of the workplane, or drag it onto the 3D view to drop it
  where you let go. Text and Box with lid ask for their sizes first.
- **Middle:** the 3D view. Drag to turn it, Shift-drag to slide it, scroll
  to zoom. The cube in the top right corner turns the view to the side you
  click, and the strip above the view says which mode it is in.
- **Right:** *Scene* lists every part (Ctrl- or Shift-click to pick more
  than one), *History* lists every step you can undo (click one to go back
  to it), and *Properties* shows the selected part's exact numbers.
- **Bottom:** what the current tool wants you to do next, and the keys
  worth knowing.

Every panel can be moved, stacked, floated or closed (bring it back from
**View → Panels**). The layout is remembered for next time, along with the
window's size.

**Ctrl+K** searches every command by name: type a few letters, then Enter.

**Themes.** **View → Theme** switches between Dark, Light, Fusion Grey,
Midnight Blue, High Contrast and Solarized straight away. **View → Theme
Editor…** starts from any of them, lets you change each colour, and saves
your own theme under a name of your choosing. Your themes are kept in
`~/.config/mesh/themes/`, and the theme you last picked is remembered.

The first time mesh starts it shows a short welcome screen; it is under
**View → Welcome Screen** after that.

## Install the launcher

    ln -sf ~/mesh/bin/mesh ~/.local/bin/mesh
    cp ~/mesh/mesh.desktop ~/.local/share/applications/

## Tools for real printed parts

Everything here is in millimetres, and everything can be undone with `Ctrl+Z`.

- **Fit (for holes).** Select a hole and pick a fit in the Properties panel:
  *Exact*, *Press fit*, *Snug fit* or *Loose fit*. A fit adds a little room on
  every side of the hole so the part that goes in actually fits after printing:
  a 10 mm snug hole comes out 10.4 mm across. Change how much room each fit adds
  under **Shape → Fit clearances…** (Press 0.1, Snug 0.2, Loose 0.4 mm per side
  to start with). On a hole made from an added model file or a group, the fit
  stretches the hole evenly, which is close but not exact.
- **Add hardware hole.** Ready-made holes for screws (plain, countersunk or
  counterbored, M2–M6), hex nut traps (M2–M6), heat-set insert pockets (M2–M5)
  and magnet pockets (10×2, 8×2, 6×2, 4×2 mm). Each is one hole you can move and
  change; its size is a drop-down in the Properties panel. The opening is at the
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

With Expert mode on:

- **Sketch → New Sketch** draws flat curves (lines, rectangles, circles,
  arcs, polygons and splines) on the workplane or an upright plane. Type each
  curve in millimetres, or turn on *Draw Lines* and click points into the
  drawing. **Sketch on a Face** draws on a clicked flat face of a part and
  shows that face's outline, which you can copy in to trace. **Change
  Sketch** redraws a sketch, or the sketch a part was made from. Sketches are
  guides: they show in orange, save with the project and undo like anything
  else, but are never printed.
- **Create → Extrude** pushes a sketch's closed outlines out of its plane,
  **Revolve** turns them around a line, **Sweep** carries them along a path
  drawn in a second sketch, and **Loft** joins the outlines of two or more
  sketches with a skin. Each makes a new part or a hole. The sketch is used up
  unless you keep it; the part keeps a copy of its curves, so its distance or
  angle stays editable in Properties.

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
| `Ctrl+K` | Search commands |
| `E` | Extrude (Expert mode) |
| `Esc` | Stop the current tool |

## Develop

    uv sync
    uv run pytest

The QML front end is `mesh/qml_app.py` (the window), `mesh/bridge.py` (what
the QML panels read and call) and `mesh/qml/Mesh/` (the panels). Icons and
Insert thumbnails are drawn by `uv run python tools/make_assets.py`; run it
again after adding a command or a shape.

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

## How this was made

mesh was vibecoded. Alexup220, who owns this repository, described what
they wanted in plain-language prompts (some of them drafted with a
prompt-writing skill called prompt-master), and Claude, Anthropic's AI
model, running as Claude Code, wrote essentially all of the code, the tests
and the documentation, this section included. Alexup220 decided what to
build, steered the design, ran the app on their own computers, reported
what was wrong, and approved each change before it was merged. They did not
write the code by hand.

The Claude Code sessions were started from threads in claude.ai Projects.
Some ran in Anthropic's cloud containers; others ran through Remote Control
on Alexup220's own Linux laptop and desktop PC, where Claude could start the
real app, drive it, and take screenshots of it.

The git history shows this. Of the commits before this section, 149 are by
"Claude" or "Claude Code"; the 5 under Alexup220's name are three GitHub merge
commits and two commits Claude made on Alexup220's machine with their git
identity, which carry a `Co-Authored-By: Claude` line.

### How it was built, in order

1. **The base app (2026-09-07 to 2026-09-10).** Claude wrote a design spec
   ([docs/superpowers/specs/2026-09-07-mesh-design.md](docs/superpowers/specs/2026-09-07-mesh-design.md))
   and a task-by-task plan from Alexup220's description, then built it one
   task at a time with tests: shapes, holes and grouping, undo, the 3D view,
   import and export, the print check. It ended with
   [docs/FOLLOWUPS.md](docs/FOLLOWUPS.md), a list of known gaps that were
   deliberately left for later.
2. **[PR #1](https://github.com/Alexup220/mesh/pull/1), 12 beginner tools
   (merged 2026-10-05).** Fits for holes, hardware holes, lay flat, place on
   a face, hollow, split, rounded shapes, bottom chamfer, repeat, box with
   lid, text and measure.
3. **[PR #2](https://github.com/Alexup220/mesh/pull/2), Expert mode
   (merged 2026-10-05).** A larger set of tools modelled on Autodesk Fusion,
   built in phases 0 to 5: sketches and Create, Modify, patterns and mirror,
   construction geometry and inspect tools, then parameters, history and
   components.
4. **[PR #3](https://github.com/Alexup220/mesh/pull/3), the QML interface
   (merged 2026-10-09).** The ribbon, Insert panel, Scene, Properties and
   History panels, Ctrl+K command search, six themes and a theme editor,
   around the same 3D view. Bugs Alexup220 found by using it (clipped menus,
   Ctrl+K search closing, a crash opening the theme editor from Ctrl+K) were
   fixed in the same PR.

Each step started from a design note in [docs/superpowers/](docs/superpowers/),
written by Claude before the code.

### What was checked

- **Automated tests.** 1887 tests, run with `uv run pytest`, all passing
  when PR #3 was merged. They run Qt off screen and do not draw the 3D view,
  so they say nothing about how it looks.
- **On-screen checks.** Claude started the app on Alexup220's machines,
  drove it with scripted clicks and keys, and looked at screenshots. This
  caught bugs the tests did not: the base build's 3D view was completely
  black after the tests had passed, and PR #3's menu and crash bugs were
  reproduced and confirmed fixed this way.
- **Use.** Alexup220 used the app on their machines and reported problems,
  which were then fixed.
- **Review.** Code review was also done by Claude, in separate review
  passes. No person has read through the code line by line.

### What was not checked

- **Printed parts.** The sizes of hardware holes (screws, nut traps,
  heat-set inserts, magnets), the fit clearances and the thread profiles were
  chosen by Claude from published standards and common values. They have
  not been confirmed against real hardware or test prints. Check them on a small test print
  before relying on them.
- **Other systems.** mesh has only been run on Linux (Arch-based, Hyprland,
  through XWayland). Windows and macOS have not been tried.
- **Approximations.** mesh works on triangle meshes, not exact curved
  surfaces. [docs/FOLLOWUPS.md](docs/FOLLOWUPS.md) lists where its results
  differ from the tools they are modelled on, and the known bugs still open.
