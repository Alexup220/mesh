"""The window's Expert mode components (the Assemble menu).

Mixed into MeshWindow through ExpertActions. What a component is, and the
rules for names and ids, are in mesh.components; this is the Components
window and the wiring: check, then change the scene as one undo step.
"""

import copy
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from mesh import components
from mesh.history import replayable
from mesh.io_formats import EXPORT_EXTS, ProjectError, export_scene
from mesh.panels import run_form
from mesh.scene import Scene

COMPONENTS_NOTE = (
    "A component keeps separate parts together under a name, without joining them: select "
    "its parts to move them together, hide it, save it for printing on its own, or copy it. "
    "A part made from a component's parts by a tool (rounding an edge, combining) stays in it."
)
NEW_COMPONENT_NOTE = (
    "The selected parts, sketches and guides become one component. A part already in another "
    "component moves to this one."
)


class ComponentsDialog(QDialog):
    """The list of components, with a button for each thing to do to the
    one chosen. Each button changes the project at once (one undo step);
    the list then shows the result."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Components")
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        self.note = QLabel(COMPONENTS_NOTE, self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.items = QListWidget(self)
        layout.addWidget(self.items)
        bar = QHBoxLayout()
        self.buttons = {}
        for key, text in (("rename", "Rename..."), ("select", "Select"), ("show", "Show or Hide"),
                          ("copy", "Copy"), ("save", "Save for Printing..."), ("break", "Break Apart")):
            button = QPushButton(text, self)
            button.clicked.connect(lambda _checked=False, k=key: self.act(k))
            bar.addWidget(button)
            self.buttons[key] = button
        layout.addLayout(bar)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        scene = self.window.document.scene
        row = self.items.currentRow()
        self.items.clear()
        self.items.addItems([components.describe(c, scene.shapes) for c in scene.components])
        if scene.components:
            self.items.setCurrentRow(min(max(row, 0), len(scene.components) - 1))
        for button in self.buttons.values():
            button.setEnabled(bool(scene.components))

    def chosen(self) -> str | None:
        row = self.items.currentRow()
        listed = self.window.document.scene.components
        return listed[row]["id"] if 0 <= row < len(listed) else None

    def act(self, key: str) -> None:
        component_id = self.chosen()
        if component_id is None:
            return
        window = self.window
        if key == "rename":
            window.ask_component_name(component_id)
        elif key == "select":
            window.select_component(component_id)
        elif key == "show":
            window.set_component_shown(component_id, not components.shown(window.document.scene.shapes,
                                                                          component_id))
        elif key == "copy":
            window.copy_component(component_id)
        elif key == "save":
            window.ask_export_component(component_id)
        elif key == "break":
            window.break_apart_component(component_id)
        self.refresh()


class ComponentActions:
    """Mixed into MeshWindow through ExpertActions."""

    COMPONENT_NEEDS_PARTS = "Select the parts to make into a component first."
    NOT_IN_A_COMPONENT = "None of the selected parts is in a component."
    NO_COMPONENTS = "There are no components yet: Assemble > New Component from Selection."

    def _carry_components(self) -> None:
        """Called on every sync: what a tool made from a component's parts
        joins that component (mesh.components.carry_over)."""
        document = self.document
        if document.action_before is not None and document.scene.components:
            components.carry_over(document.action_before, document.scene)

    def _component_problem(self, title: str, build):
        try:
            return build()
        except components.ComponentError as exc:
            self._warn(title, str(exc))
            return None

    @replayable()
    def make_component(self, name: str | None = None) -> bool:
        """The selected shapes become a new component. One undo step."""
        chosen = self._picked()
        scene = self.document.scene
        if not chosen:
            self.statusBar().showMessage(self.COMPONENT_NEEDS_PARTS)
            return False
        name = self._component_problem("Cannot make the component", lambda: components.check_name(
            components.next_name(scene.components) if name is None else name, scene.components))
        if name is None:
            return False
        self.document.snapshot("new component")
        made = {"id": components.new_id(",".join(s.id for s in chosen), {c["id"] for c in scene.components}),
                "name": name}
        scene.components = [*scene.components, made]
        for shape in chosen:
            shape.component = made["id"]
        self.sync()
        self.statusBar().showMessage(f"Made {name} from {len(chosen)} selected "
                                     f"{'part' if len(chosen) == 1 else 'parts'}.")
        return True

    def do_make_component(self) -> None:
        if not self._picked():
            self.statusBar().showMessage(self.COMPONENT_NEEDS_PARTS)
            return
        values = run_form(self, "New Component", [
            ("name", "Name", components.next_name(self.document.scene.components), {}),
        ], note=NEW_COMPONENT_NOTE)
        if values is not None:
            self.make_component(values["name"])

    def select_component(self, component_id: str) -> None:
        """Select the component's parts (no undo step)."""
        scene = self.document.scene
        scene.select([s.id for s in components.members(scene.shapes, component_id)])
        self.sync()

    def do_select_component(self) -> None:
        """Add the rest of each selected part's component to the selection."""
        scene = self.document.scene
        held = {s.component for s in scene.selected() if s.component}
        if not held:
            self.statusBar().showMessage(self.NOT_IN_A_COMPONENT)
            return
        scene.select(list(scene.selection) + [s.id for s in scene.shapes
                                              if s.component in held and s.id not in scene.selection])
        self.sync()

    @replayable()
    def leave_component(self) -> bool:
        """Take the selected parts out of their components. One undo step."""
        chosen = [s for s in self.document.scene.selected() if s.component]
        if not chosen:
            self.statusBar().showMessage(self.NOT_IN_A_COMPONENT)
            return False
        self.document.snapshot("take out of component")
        for shape in chosen:
            shape.component = ""
        self.sync()
        return True

    @replayable()
    def rename_component(self, component_id: str, name: str) -> bool:
        scene = self.document.scene
        found = self._component_problem("Cannot rename the component", lambda: (
            components.get(scene.components, component_id),
            components.check_name(name, scene.components, component_id)))
        if found is None:
            return False
        component, name = found
        if component["name"] == name:
            return False
        self.document.snapshot("rename component")
        scene.components = [{**c, "name": name} if c["id"] == component_id else c for c in scene.components]
        self.sync()
        return True

    def ask_component_name(self, component_id: str) -> bool:
        scene = self.document.scene
        try:
            current = components.get(scene.components, component_id)["name"]
        except components.ComponentError:
            return False
        values = run_form(self, "Rename Component", [("name", "Name", current, {})])
        return values is not None and self.rename_component(component_id, values["name"])

    @replayable()
    def set_component_shown(self, component_id: str, shown: bool) -> bool:
        """Show or hide all of a component's parts. One undo step."""
        parts = components.members(self.document.scene.shapes, component_id)
        if not parts or all(s.visible == bool(shown) for s in parts):
            return False
        self.document.snapshot("show component" if shown else "hide component")
        for shape in parts:
            shape.visible = bool(shown)
        self.sync()
        return True

    @replayable()
    def copy_component(self, component_id: str) -> bool:
        """An independent copy of a component, beside it. One undo step."""
        scene = self.document.scene
        made = self._component_problem("Cannot copy the component", lambda: components.copied(
            scene.shapes, scene.components, component_id))
        if made is None:
            return False
        component, copies = made
        self.document.snapshot("copy component")
        scene.components = [*scene.components, component]
        for shape in copies:
            scene.add(shape)
        scene.select([s.id for s in copies])
        self.sync()
        return True

    @replayable()
    def break_apart_component(self, component_id: str) -> bool:
        """End a component; its parts stay, in no component. One undo step."""
        scene = self.document.scene
        if component_id not in {c["id"] for c in scene.components}:
            return False
        self.document.snapshot("break apart component")
        scene.components = [c for c in scene.components if c["id"] != component_id]
        for shape in components.members(scene.shapes, component_id):
            shape.component = ""
        self.sync()
        return True

    def export_component(self, component_id: str, path) -> None:
        """Save one component's parts for printing (hidden ones too).
        Raises ProjectError, as saving the whole project for printing does."""
        scene = self.document.scene
        parts = [copy.deepcopy(s) for s in components.members(scene.shapes, component_id)]
        for part in parts:
            part.visible = True
        export_scene(Scene(shapes=parts, fit_clearances=dict(scene.fit_clearances)), path)

    def ask_export_component(self, component_id: str) -> None:
        try:
            name = components.get(self.document.scene.components, component_id)["name"]
        except components.ComponentError:
            return
        pattern = "Printable models (" + " ".join(f"*{e}" for e in EXPORT_EXTS) + ")"
        path, _ = QFileDialog.getSaveFileName(self, f"Save {name} for Printing", f"{name}.stl", pattern)
        if not path:
            return
        try:
            self.export_component(component_id, path)
        except ProjectError as exc:
            self._warn("Cannot save", str(exc))
            return
        self.statusBar().showMessage(f"Saved {Path(path).name}")

    def do_components(self) -> None:
        if not self.document.scene.components:
            self.statusBar().showMessage(self.NO_COMPONENTS)
            return
        dialog = ComponentsDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
