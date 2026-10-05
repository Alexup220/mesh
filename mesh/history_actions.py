"""The window's Expert mode history list (Modify > History).

Mixed into MeshWindow through ExpertActions. What a step is, how it is
recorded and how its changes are applied is in mesh.history; this is the
History window, the forms that change a step's settings, and the replay:
work the project out again from where the history started, step by step,
running each tool again on the parts as they are by then.
"""

import copy
from types import SimpleNamespace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from mesh import components, history, parameters
from mesh.panels import run_form
from mesh.scene import Document, Scene

HISTORY_NOTE = (
    "Every change to the project since the history started, in order. Change a step's "
    "settings, or remove a step, and the whole project is worked out again: tools (Extrude, "
    "Round an Edge, Combine, the patterns and more) run again on the parts as they are by "
    "then, so later steps follow. Other steps (adding a shape, moving, typing in the Details "
    "panel) do again what they did."
)
NOT_KEPT_NOTE = (
    "This project keeps no history yet. Start one, and every change from then on is listed "
    "here, ready to be changed or removed."
)
STEP_NOTE = "The project is worked out again from this step on, with these settings."


def _filled(fields, values: dict):
    """`fields` with their starting values taken from `values` (a number
    kept the kind of number its box takes)."""
    out = []
    for key, label, default, options in fields:
        value = values.get(key, default)
        if isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
        elif isinstance(default, int) and not isinstance(default, bool) and isinstance(value, float):
            value = int(round(value))
        out.append((key, label, value, options))
    return out


def _without(fields, *keys):
    return [f for f in fields if f[0] not in keys]


def _results(args: dict) -> dict:
    return {"result": "hole" if args.get("hole") else "part", "keep_sketch": bool(args.get("keep_sketch"))}


def _from_results(values: dict) -> dict:
    return {"hole": values["result"] == "hole", "keep_sketch": values["keep_sketch"]}


def _same(values: dict, _args: dict) -> dict:
    return values


def editors() -> dict:
    """The tools whose steps can be changed: method -> (form title, the
    form's fields from the step's settings, the settings from the form's
    values). Each uses the tool's own form."""
    from mesh import construct_actions as ca
    from mesh import expert_actions as ea
    from mesh import modify_actions as ma
    from mesh import panels
    from mesh import pattern_actions as pa

    nothing = [SimpleNamespace(id="", name="")]
    results = (lambda a: _filled(ea.loft_fields(2), _results(a)), lambda v, _a: _from_results(v))
    return {
        "extrude_selected": (
            "Extrude",
            lambda a: _filled(ea.extrude_fields("the selected plane" if a.get("to_plane") else None),
                              {**a, **_results(a), "extent": "plane" if a.get("to_plane") else "distance"}),
            lambda v, _a: {"distance": v["distance"], "side": v["side"], "taper": v["taper"],
                           "to_plane": v.get("extent") == "plane", **_from_results(v)}),
        "revolve_selected": ("Revolve",
                             lambda a: _filled(_without(ea.revolve_fields([(a["axis"], "")]), "axis"),
                                               {**a, **_results(a)}),
                             lambda v, _a: {"angle": v["angle"], **_from_results(v)}),
        "sweep_selected": ("Sweep", *results),
        "loft_selected": ("Loft", *results),
        "thread_selected": ("Thread", lambda a: _filled(ea.thread_fields(a["length"], a["pitch"]), a), _same),
        "move_copy_selected": ("Move or Copy", lambda a: _filled(ma.move_copy_fields(), a), _same),
        "scale_selected": ("Scale", lambda a: _filled(ma.scale_fields(), a), _same),
        "combine_selected": ("Combine", lambda a: _filled(_without(ma.combine_fields(nothing), "target"), a),
                             _same),
        "split_body_selected": ("Split Body",
                                lambda a: _filled(_without(ma.split_body_fields(nothing), "part"), a), _same),
        "shell_face": ("Shell", lambda a: _filled(ma.shell_fields(), a), _same),
        "push_pull_face": ("Push/Pull", lambda a: _filled(ma.push_pull_fields(), a), _same),
        "round_edge": ("Round an Edge", lambda a: _filled(ma.fillet_fields(), a), _same),
        "bevel_edge": ("Bevel an Edge", lambda a: _filled(ma.chamfer_fields(), a), _same),
        "draft_selected": ("Slope the Sides",
                           lambda a: ma.draft_fields(abs(float(a["angle"])), "out" if a["angle"] < 0 else "in"),
                           lambda v, _a: {"angle": v["angle"] * (-1.0 if v["direction"] == "out" else 1.0)}),
        "rectangular_pattern_selected": ("Pattern in Rows", lambda a: _filled(pa.rectangular_fields(), a), _same),
        "circular_pattern_selected": (
            "Pattern Around a Line", lambda a: _filled(pa.circular_fields(a["centre"]), a),
            lambda v, _a: {"count": v["count"], "angle": v["angle"], "axis": v["axis"],
                           "centre": [v["centre_x"], v["centre_y"], v["centre_z"]]}),
        "path_pattern_selected": (
            "Pattern Along a Path",
            lambda a: _filled(pa.path_fields(), {**a, "even": a["spacing"] is None,
                                                 "spacing": a["spacing"] or 10.0}),
            lambda v, _a: {"count": v["count"], "spacing": None if v["even"] else v["spacing"],
                           "follow": v["follow"]}),
        "mirror_copy_selected": ("Mirror", lambda a: [("plane", "Mirror across", a["plane"],
                                                       {"choices": pa.MIRROR_PLANES[1:]})], _same),
        "plane_at_distance_selected": (
            "Plane at a Distance", lambda a: _filled(_without(ca.plane_distance_fields(), "source"), a), _same),
        "plane_from_face": (
            "Plane at a Distance", lambda a: _filled(_without(ca.plane_distance_fields(), "source"), a), _same),
        "plane_at_angle_selected": (
            "Plane at an Angle", lambda a: _filled(_without(ca.plane_angle_fields([("z", "")]), "line"), a),
            _same),
        "hollow_selected": ("Hollow out", lambda a: _filled(panels.hollow_fields(True), a), _same),
        "split_selected": ("Split part", lambda a: _filled(panels.split_fields((0.0, 0.0, 0.0)), a), _same),
        "repeat_row_selected": ("Repeat in a row", lambda a: _filled(panels.repeat_row_fields(), a), _same),
        "repeat_circle_selected": (
            "Repeat in a circle",
            lambda a: _filled(panels.repeat_circle_fields((0.0, 0.0)),
                              {**a, "centre_x": a["centre"][0], "centre_y": a["centre"][1]}),
            lambda v, _a: {"count": v["count"], "radius": v["radius"], "angle": v["angle"],
                           "centre": [v["centre_x"], v["centre_y"]]}),
    }


class HistoryDialog(QDialog):
    """The history list, with buttons to change or remove a step and to
    start or stop keeping the history. Each button changes the project
    at once (one undo step each); the list then shows the result."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("History")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.steps = QListWidget(self)
        self.steps.itemDoubleClicked.connect(lambda _item: self.change())
        layout.addWidget(self.steps)
        bar = QHBoxLayout()
        self.start_button = QPushButton("Start Keeping a History", self)
        self.start_button.clicked.connect(self.start)
        self.change_button = QPushButton("Change...", self)
        self.change_button.clicked.connect(self.change)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self.remove)
        self.stop_button = QPushButton("Stop Keeping It", self)
        self.stop_button.clicked.connect(self.stop)
        for button in (self.start_button, self.change_button, self.remove_button, self.stop_button):
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        kept = self.window.document.scene.history is not None
        steps = self.window.history_steps()
        row = self.steps.currentRow()
        self.note.setText(HISTORY_NOTE if kept else NOT_KEPT_NOTE)
        self.steps.clear()
        self.steps.addItems([f"{number}. {history.describe(step)}" for number, step in enumerate(steps, 1)])
        if steps:
            self.steps.setCurrentRow(min(max(row, 0), len(steps) - 1))
        self.start_button.setVisible(not kept)
        for button in (self.change_button, self.remove_button):
            button.setVisible(kept)
            button.setEnabled(bool(steps))
        self.stop_button.setVisible(kept)

    def _row(self) -> int | None:
        row = self.steps.currentRow()
        return row if row >= 0 else None

    def start(self) -> None:
        self.window.start_history()
        self.refresh()

    def stop(self) -> None:
        self.window.stop_history()
        self.refresh()

    def change(self) -> None:
        row = self._row()
        if row is not None:
            self.window.ask_step_change(row)
            self.refresh()

    def remove(self) -> None:
        row = self._row()
        if row is not None:
            self.window.remove_history_step(row)
            self.refresh()


class HistoryActions:
    """Mixed into MeshWindow through ExpertActions."""

    HISTORY_STARTED = "From now on, every change is kept in the history (Modify > History)."
    HISTORY_STOPPED = "The history is no longer kept. The parts stay as they are."
    STEP_FIXED = "That step has no settings to change. It can be removed."

    def history_steps(self) -> list:
        """The steps of the history kept, each with what it changed."""
        self.document.settle()
        kept = self.document.scene.history
        return kept["steps"] if kept is not None else []

    def _replace_scene(self, label: str, scene) -> None:
        """One undo step that is not itself a step of the history."""
        self.document.recording = False
        try:
            self.document.snapshot(label)
        finally:
            self.document.recording = True
        self.document.scene = scene
        # Worked out already: nothing in it was made by the newest change.
        self.document.action_before = None
        self._clear_tool()
        self.sync()

    def start_history(self) -> bool:
        if self.document.scene.history is not None:
            return False
        scene = copy.deepcopy(self.document.scene)
        scene.history = history.start(scene)
        self._replace_scene("keep a history", scene)
        self.statusBar().showMessage(self.HISTORY_STARTED)
        return True

    def stop_history(self) -> bool:
        if self.document.scene.history is None:
            return False
        self.document.settle()
        scene = copy.deepcopy(self.document.scene)
        scene.history = None
        self._replace_scene("stop the history", scene)
        self.statusBar().showMessage(self.HISTORY_STOPPED)
        return True

    # --- Working the project out again -------------------------------------------------

    def _replayed(self, steps, rows=None, numbers=None) -> Scene:
        """The project worked out again from the history's start through
        `steps`, with the parameters `rows` (or the current ones). Raises
        history.HistoryError, saying which step (by its number in
        `numbers`, or its place) can't be worked out."""
        kept = self.document.scene.history
        scene = Scene.from_dict(copy.deepcopy(kept["base"]))
        scene.parameters = copy.deepcopy(self.document.scene.parameters if rows is None else rows)
        try:
            known = parameters.values(scene.parameters)
            parameters.apply_links(scene.shapes, known)
        except parameters.ParameterError as exc:
            raise history.HistoryError(str(exc)) from None
        scratch = Document(scene)
        scratch.recording = False
        saved = {name: self.__dict__.get(name) for name in ("document", "sync", "_warn")}
        warned: list = []
        self.document = scratch
        self.sync = lambda *_a, **_k: None
        self._warn = lambda _title, text: warned.append(text)
        done = []
        try:
            for number, step in zip(numbers or range(1, len(steps) + 1), steps):
                try:
                    effect = self._replay_step(scratch, step, warned)
                    parameters.apply_links(scratch.scene.shapes, known)
                except (history.HistoryError, parameters.ParameterError) as exc:
                    raise history.HistoryError(
                        f"Step {number} ({history.describe(step)}) can't be worked out: {exc}"
                    ) from None
                done.append({"label": step["label"], "call": copy.deepcopy(step["call"]), "effect": effect})
        finally:
            for name, value in saved.items():
                if value is None:
                    self.__dict__.pop(name, None)
                else:
                    self.__dict__[name] = value
        result = scratch.scene
        result.history = {"base": kept["base"], "steps": done}
        result.select([i for i in self.document.scene.selection])
        return result

    def _replay_step(self, scratch, step, warned) -> dict:
        """Do one step again on `scratch`; what it changed this time."""
        scene = scratch.scene
        call = step["call"]
        if call is None:
            history.apply_changes(scene, step["effect"] or {})
            return copy.deepcopy(step["effect"])
        method = getattr(self, call["method"], None)
        known = {s.id for s in scene.shapes}
        if method is None or any(i not in known for i in call["picked"]):
            raise history.HistoryError("a part it was used on is no longer there.")
        scene.select(call["picked"])
        args = history.placed_args(call, getattr(method, "replay_faces", ()), scene, scene.fit_clearances)
        before = copy.deepcopy(scene)
        revision = scratch.revision
        warned.clear()
        self.statusBar().clearMessage()
        method(**args)
        if scratch.revision == revision:
            reason = warned[-1] if warned else self.statusBar().currentMessage()
            raise history.HistoryError(reason or "it no longer applies to the parts it was used on.")
        scene = scratch.scene
        history.rename_added(scene, {s.id for s in before.shapes},
                             [d["id"] for d in (step["effect"] or {}).get("added", [])])
        components.carry_over(before, scene)  # as the window's sync does
        return history.changes(before, scene)

    def _rework(self, title: str, label: str, steps, rows=None, numbers=None) -> bool:
        """Replace the project with it worked out again (one undo step), or
        say why it can't be."""
        try:
            scene = self._replayed(steps, rows, numbers)
        except history.HistoryError as exc:
            self._warn(title, str(exc))
            return False
        self._replace_scene(label, scene)
        return True

    # --- Changing the history -----------------------------------------------------------

    def change_history_step(self, index: int, settings: dict) -> bool:
        """Give step `index` (from 0) new settings and work the project out
        again."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps) or steps[index]["call"] is None:
            return False
        steps[index]["call"]["args"].update(history.plain(settings))
        return self._rework("Cannot change the step", "change a step", steps)

    def remove_history_step(self, index: int) -> bool:
        """Take step `index` (from 0) out and work the project out again."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps):
            return False
        del steps[index]
        numbers = [n for n in range(1, len(steps) + 2) if n != index + 1]
        return self._rework("Cannot remove the step", "remove a step", steps, numbers=numbers)

    def step_editor(self, index: int):
        """(form title, fields, settings from values) for step `index`, or
        None if it has no settings to change."""
        steps = self.history_steps()
        if not 0 <= index < len(steps) or steps[index]["call"] is None:
            return None
        call = steps[index]["call"]
        found = editors().get(call["method"])
        if found is None:
            return None
        title, fields, back = found
        return title, fields(call["args"]), lambda values: back(values, call["args"])

    def ask_step_change(self, index: int) -> bool:
        editor = self.step_editor(index)
        if editor is None:
            self.statusBar().showMessage(self.STEP_FIXED)
            return False
        title, fields, back = editor
        values = run_form(self, f"Change {title}", fields, note=STEP_NOTE)
        return values is not None and self.change_history_step(index, back(values))

    def do_history(self) -> None:
        dialog = HistoryDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
