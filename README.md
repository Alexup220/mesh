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
