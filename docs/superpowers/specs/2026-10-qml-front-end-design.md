# QML front end — design note (2026-10-05)

## Shape of it

- **The 3D view stays VTK.** VTK has no Qt Quick item for Python (only the
  C++ `QQuickVTKItem`), and its Linux backend draws through X11 into a real
  native window. So the view can't live inside a QML scene. `QmlWindow`
  (mesh/qml_app.py) is a thin `QMainWindow` whose every other visible part
  is QML: one `QQuickWidget` per panel, all sharing one `QQmlEngine`. The
  shared engine means one `Theme` singleton and one `bridge` for every panel
  and dialog.
- **`QmlWindow` is `MeshWindow`.** It subclasses the existing window and
  only takes the widget menu bar, docks, toolbar and status bar out of
  sight. Every QAction, shortcut, handler, refusal message and undo rule is
  the existing code. The QML front end triggers those QActions by key, so
  nothing is reimplemented and the existing tests keep testing the real
  behaviour.
- **The bridge (mesh/bridge.py)** turns the window into plain lists and maps
  for QML: `commands` (key → label, tip, shortcut, enabled, checked, icon),
  `menus` (walked from the hidden QMenuBar, so new menu items appear
  without any QML change), `ribbon`, `outliner`, `properties`, `history`,
  `status`, `mode`, and the theme. QML calls back with `trigger(key)`,
  `insert(key)`, `select(id, additive)`, `setField(field, value)`,
  `undoTo(index)`, and the theme slots.
- **Properties go through the hidden inspector.** `setField` types the
  value into the inspector's own control, so an edit takes exactly the
  inspector's path: its range, its checks, one undo step per burst, and the
  same coalesced sync. The properties model is read back from that
  inspector, so the fields shown always match.
- **Forms.** `panels.run_form` asks the parent's `ask_form` when it has one.
  `QmlWindow.ask_form` shows FormDialog.qml in a modal QML window and waits
  in a local event loop, returning the same values dict, so every tool
  dialog (Hollow out, Split, patterns, the expert tools) uses QML with no
  change to its code. The sketch window is still the widget dialog (themed
  by stylesheet), and so are message boxes and the file and colour
  choosers.

## Drawing

Qt Quick draws in software (`QQuickWindow.setGraphicsApi(Software)` at
the top of mesh/qml_app.py). VTK makes its own OpenGL context current
behind Qt's back, so with OpenGL Qt Quick's drawing landed in the 3D view
and the panels stayed empty. Only visible on a real screen; offscreen runs
never showed it.

## Core vs GUI

- Pure: `mesh/themes.py` (the six built-in themes, custom theme files in
  `~/.config/mesh/themes/`), `mesh/ui_catalog.py` (command keys, icon names,
  ribbon layout, palette, Insert items). Both are on the purity test's
  CORE list.
- `mesh/settings.py` gains `theme` and `layout`, written only when they
  differ from a fresh install, so an existing settings file is unchanged
  until the user changes either.
- `Document` gains `undo_labels` / `redo_labels`, kept in step with its
  stacks, for the visible history.

## Undo

Nothing new mutates the scene except through existing MeshWindow methods.
Inserting a thumbnail is `add_shape` (one "add" step). History jumps call
`Document.undo` / `redo` in a loop, then one sync. Theme and layout changes
are preferences, not edits: no undo step.

## Popups

Menus, drop-downs and tooltips use `popupType: Popup.Window` so they open in
their own small windows instead of being cut off at the edge of the panel
they belong to. Menus are built lazily on first open after their entries
change. Before that, switching Expert mode rebuilt hundreds of menu items
and took seconds.

## Assets

`tools/make_assets.py` writes `mesh/assets/icons/*.svg` (hand-written line
drawings in two placeholder colours that the icon image provider swaps
for the theme's text and highlight colours) and
`mesh/assets/thumbnails/*.svg` (each Insert item's real triangles from
`shape_geometry`, flat-shaded from the 3D view's home angle). Nothing is
downloaded.
