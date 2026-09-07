# mesh — Design Spec

**Date:** 2026-09-07
**Status:** Approved
**Target:** Arch Linux / Hyprland / Wayland

## Purpose

A 3D modeling application for people who have never modeled anything. A beginner
places shapes on a workplane, combines and cuts them, and exports a printable STL
in millimetres.

Success criterion: a first-time user models a simple bracket in five minutes
without reading documentation.

## Non-Goals

Explicitly out of scope. Each of these is a known cause of death for "simple
modeler" projects:

- Sculpting and dynamic remeshing
- PBR materials, lighting rigs, rendering
- Animation
- Parametric sketch constraints
- Cloud sync, accounts, collaboration
- A plugin system
- Text-to-3D generation

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12 (pinned) | Library ecosystem for mesh work is unmatched |
| Window / UI | PySide6 (Qt 6) | Native Wayland window; no browser, no webkit GPU risk |
| Viewport | VTK 9.6 via `QVTKRenderWindowInteractor` | Ships picking, camera, and manipulator widgets |
| Booleans | `manifold3d` | Guarantees watertight output; the engine Blender 4.x uses |
| Mesh I/O | `trimesh` | Reads and writes every format in scope |
| Environment | `uv` venv in project dir | Fully isolated; no system Python pollution |

Python 3.12 rather than the system 3.14 because PySide6 and VTK wheels lag new
CPython releases.

## Core Design Decisions

### Solid vs Hole is the primary boolean interface

Every shape carries an `is_hole` flag. Selecting several shapes and pressing
**Group** merges the solids and subtracts the holes.

This replaces the boolean-operator mental model entirely. A beginner never learns
"boolean difference"; they learn "this shape is a hole." Explicit Union,
Subtract, and Intersect remain available in a menu for users who want them, but
the flag is the primary path and the one the UI teaches.

### Shapes never float by accident

New shapes are placed on the workplane at Z=0. Lifting a shape off the plane
requires a deliberate drag on a dedicated height handle, separate from the move
handles.

The single most common beginner failure in 3D tools is parts hovering invisibly
in space. Making elevation a distinct, explicit gesture eliminates it.

### Every gesture has a numeric equivalent

Anything achievable by dragging is also typeable as a millimetre value in the
inspector. This is what separates a toy from a tool usable for real printed
parts, and it costs almost nothing because the data model is parametric.

### Geometry is derived, never authoritative

`Shape` stores parameters and a transform. Triangle geometry is computed from
those and cached. Undo, save/load, and the numeric inspector are then correct by
construction rather than by careful synchronisation.

## Architecture

```
~/mesh/
  pyproject.toml          uv-managed, Python 3.12 pinned
  mesh/
    __main__.py           entry point
    app.py                QMainWindow, menus, action wiring
    scene.py              document model + undo stack
    shapes.py             primitive definitions and mesh generation
    ops.py                booleans, align, mirror, duplicate
    io_formats.py         import, export, project save/load
    viewport.py           VTK render widget, picking, grid, camera
    gizmo.py              vtkBoxWidget2 wrapper -> Shape transform
    panels.py             shape shelf (left), numeric inspector (right)
    theme.py              Qt stylesheet + VTK colour palette
    resources/            icons
  bin/mesh                launcher script
  mesh.desktop            application menu entry
  tests/
```

Module boundaries are drawn so that `scene`, `shapes`, `ops`, and `io_formats`
have no Qt or VTK imports. They are pure data and geometry, fully testable
headless. All GUI dependency lives in `app`, `viewport`, `gizmo`, `panels`, and
`theme`.

## Data Model

```python
Shape = {
    id:        str      # uuid
    name:      str
    kind:      str      # "primitive" | "imported" | "group"
    params:    dict     # primitive dimensions, blob ref for imported,
                        # or {children: [Shape], cached_mesh: blob} for group
    transform: 4x4      # position, rotation, scale
    color:     str
    is_hole:   bool
    visible:   bool
}

Scene = {
    shapes:       [Shape]   # ordered
    selection:    [str]     # shape ids
    build_volume: (x, y, z) # default (220, 220, 250)
    snap_mm:      float     # default 1.0
}
```

### Undo

Full scene snapshots, 50 levels deep. Scenes hold at most a few hundred shapes,
so a snapshot costs microseconds. A command pattern would add indirection for no
measurable benefit.

## Interaction

**Shape shelf (left):** cube, sphere, cylinder, cone, torus, tube, wedge,
pyramid. Click places at origin on the workplane.

**Viewport:** left-click selects, shift-click extends selection. The gizmo
provides face handles to move, corner handles to scale, a ring to rotate, and a
cone handle to raise off the plane. Movement snaps to 1 mm by default, toggleable.

**Inspector (right):** position XYZ, size W/D/H, rotation in degrees, colour, and
the Solid/Hole toggle. All values in millimetres.

**Camera:** middle-drag orbits, shift+middle pans, wheel zooms. Top / Front /
Right / Home preset buttons are mandatory, not decorative — beginners lose
orientation in 3D within seconds and need a guaranteed way back.

**Bottom bar:** Undo, Redo, Group, Ungroup, Align, Mirror, Duplicate.

### Group and Ungroup

**Group** takes the selected shapes, evaluates the boolean (solids united, holes
subtracted), and replaces them with a single shape of `kind="group"`. That shape
retains the original children in its params alongside the evaluated mesh.

**Ungroup** discards the evaluated mesh and restores the children to the scene.
Grouping is therefore always reversible, independently of the undo stack — which
matters because grouping is the operation beginners perform most and regret most.

Group shapes may themselves be grouped, so the children list nests.

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+G` / `Ctrl+Shift+G` | Group / Ungroup |
| `Ctrl+D` | Duplicate |
| `Delete` | Delete selection |
| `H` | Toggle Solid/Hole on selection |
| `Ctrl+S` / `Ctrl+O` | Save / Open project |
| `Ctrl+E` | Export |
| `Ctrl+A` | Select all |
| `Home` | Reset camera |
| `1` `3` `7` | Front / Right / Top view |
| `F` | Frame selection |

The numeric view keys follow Blender's numpad convention, so the muscle memory
transfers to Blender later.

## Print Safety

The status bar permanently displays:

- Watertight: yes / no
- Bounding box in mm, compared against the configured build volume

The bounding box display turns red when the model will not fit. Export runs a
manifold repair pass first and refuses to write a mesh that is not watertight,
rather than emitting a silently broken STL.

## File Formats

**Import:** STL, OBJ, 3MF, PLY, GLB, GLTF, OFF, DAE — all via trimesh. An
imported mesh becomes a shape with `kind="imported"` and baked geometry. When a
file's dimensions suggest metres or inches, prompt for a unit conversion.

**Export:** STL (binary), 3MF, OBJ.

**Project:** `.mesh` — a JSON document holding the shape list, with imported
geometry embedded as compressed binary blobs. One file, no sidecars, no broken
external references.

## Testing

pytest, headless.

Real coverage on the pure modules:

- `shapes` — generated primitives are watertight, dimensions match parameters
- `ops` — boolean results asserted by volume and watertightness
- `scene` — undo/redo correctness, selection invariants
- `io_formats` — one import test per supported format, save/load round-trip

The GUI modules get an offscreen construction smoke test only. Simulating Qt
event sequences costs more maintenance than it catches.

## Installation

`uv sync` in `~/mesh`, `bin/mesh` symlinked onto PATH, and `mesh.desktop`
installed for the application launcher.

## Build Order

1. **Skeleton** — window, viewport, grid, camera presets, primitive placement,
   selection, gizmo, numeric inspector, undo.
2. **Booleans** — Solid/Hole flag, Group/Ungroup, align, mirror, duplicate.
3. **I/O** — importers, STL/3MF/OBJ export, project save/load, printability checks.
4. **Polish** — theme, icons, keyboard shortcuts, first-run overlay, desktop entry.
