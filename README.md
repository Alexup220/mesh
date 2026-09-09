# mesh

Easy 3D modeling for 3D printing.

Drop shapes on the workplane, mark the ones you want removed as **holes**,
press **Group**, and save a printable STL. Everything is in millimetres.

## Run

    ~/mesh/bin/mesh

## Install the launcher

    ln -sf ~/mesh/bin/mesh ~/.local/bin/mesh
    cp ~/mesh/mesh.desktop ~/.local/share/applications/

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
