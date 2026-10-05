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

from mesh import components, history, parameters, sketch
from mesh.builders import BuildError
from mesh.panels import run_form
from mesh.scene import Document, Scene
from mesh.shapes import shape_geometry

HISTORY_NOTE = (
    "Every change to the project since the history started, in order. Change a step's "
    "settings or the parts it was used on, skip it, move it or remove it, and the whole "
    "project is worked out again: tools (Extrude, Round an Edge, Combine, the patterns and "
    "more) run again on the parts as they are by then, so later steps follow. Other steps "
    "(adding a shape, moving, typing in the Details panel) do again what they did. To use a "
    "step on other parts, select them first, then choose the step and Use on Selection."
)
NOT_KEPT_NOTE = (
    "This project keeps no history yet. Start one, and every change from then on is listed "
    "here, ready to be changed or removed."
)
STEP_NOTE = "The project is worked out again from this step on, with these settings."
SKETCH_STEP_NOTE = (
    "The curves as this step drew them. Change them and the project is worked out again from "
    "here: parts later made from this sketch follow."
)
FORMULAS_NOTE = (
    "Type a number, or a formula of your parameters (such as width / 2). A setting given by a "
    "formula follows the parameters: change them and the project is worked out again. A count "
    "is rounded to a whole number. Changing the setting in Change... ends its formula."
)


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


def _numbers(skip) -> str:
    """Copy numbers to leave out, as the text their box shows."""
    if isinstance(skip, (list, tuple)):
        return ", ".join(str(n) for n in skip)
    return str(skip or "")


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
        "extrude_selected": ("Extrude", lambda a: _filled(ea.extrude_fields(), {**a, **_results(a)}),
                             lambda v, _a: {"distance": v["distance"], "side": v["side"], **_from_results(v)}),
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
        "shell_face": ("Shell", lambda a: _filled(_without(ma.shell_fields(), "faces"), a), _same),
        "push_pull_face": ("Push/Pull", lambda a: _filled(ma.push_pull_fields(), a), _same),
        "round_edge": ("Round an Edge", lambda a: _filled(_without(ma.fillet_fields(), "edges"), a), _same),
        "bevel_edge": ("Bevel an Edge", lambda a: _filled(_without(ma.chamfer_fields(), "edges"), a), _same),
        "draft_selected": ("Slope the Sides",
                           lambda a: ma.draft_fields(abs(float(a["angle"])), "out" if a["angle"] < 0 else "in"),
                           lambda v, _a: {"angle": v["angle"] * (-1.0 if v["direction"] == "out" else 1.0)}),
        "rectangular_pattern_selected": (
            "Pattern in Rows",
            lambda a: _filled(pa.rectangular_fields("axis" if "selected" in (a["axis"], a["axis2"]) else None),
                              {**a, "skip": _numbers(a.get("skip"))}),
            _same),
        "circular_pattern_selected": (
            "Pattern Around a Line",
            lambda a: _filled(pa.circular_fields(a["centre"]), {**a, "skip": _numbers(a.get("skip"))}),
            lambda v, _a: {"count": v["count"], "angle": v["angle"], "axis": v["axis"],
                           "centre": [v["centre_x"], v["centre_y"], v["centre_z"]],
                           "symmetric": v["symmetric"], "skip": v["skip"]}),
        "path_pattern_selected": (
            "Pattern Along a Path",
            lambda a: _filled(pa.path_fields(), {**a, "even": a["spacing"] is None,
                                                 "spacing": a["spacing"] or 10.0,
                                                 "skip": _numbers(a.get("skip"))}),
            lambda v, _a: {"count": v["count"], "spacing": None if v["even"] else v["spacing"],
                           "follow": v["follow"], "skip": v["skip"]}),
        "mirror_copy_selected": ("Mirror", lambda a: _filled(
            [("plane", "Mirror across", a["plane"], {"choices": pa.MIRROR_PLANES[1:]}), pa.JOIN_FIELD], a),
            _same),
        "mirror_across_face": ("Mirror", lambda a: _filled([pa.JOIN_FIELD], a), _same),
        "plane_at_distance_selected": (
            "Plane at a Distance", lambda a: _filled(_without(ca.plane_distance_fields(), "source"), a), _same),
        "plane_from_face": (
            "Plane at a Distance", lambda a: _filled(_without(ca.plane_distance_fields(), "source"), a), _same),
        "plane_at_angle_selected": (
            "Plane at an Angle", lambda a: _filled(_without(ca.plane_angle_fields([("z", "")]), "line"), a),
            _same),
        "plane_along_path_selected": (
            "Plane Along a Path",
            lambda a: _filled(ca.plane_path_fields(), {**a, "from": "end" if a["from_end"] else "start"}),
            lambda v, _a: {"distance": v["distance"], "from_end": v["from"] == "end"}),
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
        self.resize(820, 460)
        layout = QVBoxLayout(self)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.steps = QListWidget(self)
        self.steps.itemDoubleClicked.connect(lambda _item: self.change())
        self.steps.currentRowChanged.connect(lambda _row: self._name_skip())
        layout.addWidget(self.steps)
        bar = QHBoxLayout()
        self.start_button = QPushButton("Start Keeping a History", self)
        self.start_button.clicked.connect(self.start)
        self.change_button = QPushButton("Change...", self)
        self.change_button.clicked.connect(self.change)
        self.formulas_button = QPushButton("Use Parameters...", self)
        self.formulas_button.clicked.connect(self.formulas)
        self.retarget_button = QPushButton("Use on Selection", self)
        self.retarget_button.clicked.connect(self.retarget)
        self.skip_button = QPushButton("Skip", self)
        self.skip_button.clicked.connect(self.skip)
        self.up_button = QPushButton("Move Up", self)
        self.up_button.clicked.connect(lambda: self.move(-1))
        self.down_button = QPushButton("Move Down", self)
        self.down_button.clicked.connect(lambda: self.move(1))
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self.remove)
        self.stop_button = QPushButton("Stop Keeping It", self)
        self.stop_button.clicked.connect(self.stop)
        for button in (self.change_button, self.formulas_button, self.retarget_button, self.skip_button,
                       self.up_button, self.down_button, self.remove_button):
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        keeping = QHBoxLayout()
        for button in (self.start_button, self.stop_button):
            keeping.addWidget(button)
        keeping.addStretch(1)
        layout.addLayout(keeping)
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
        for button in (self.change_button, self.formulas_button, self.retarget_button, self.skip_button,
                       self.remove_button):
            button.setVisible(kept)
            button.setEnabled(bool(steps))
        for button in (self.up_button, self.down_button):
            button.setVisible(kept)
            button.setEnabled(len(steps) > 1)
        self.stop_button.setVisible(kept)
        self._name_skip()

    def _name_skip(self) -> None:
        """The skip button says what it will do to the chosen step."""
        steps = self.window.history_steps()
        row = self.steps.currentRow()
        off = 0 <= row < len(steps) and bool(steps[row].get("off"))
        self.skip_button.setText("Use Again" if off else "Skip")

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

    def formulas(self) -> None:
        row = self._row()
        if row is not None:
            self.window.ask_step_formulas(row)
            self.refresh()

    def retarget(self) -> None:
        row = self._row()
        if row is not None:
            self.window.retarget_history_step(row, self.window.document.scene.selection)
            self.refresh()

    def skip(self) -> None:
        row = self._row()
        if row is not None:
            steps = self.window.history_steps()
            self.window.skip_history_step(row, not steps[row].get("off"))
            self.refresh()

    def move(self, by: int) -> None:
        row = self._row()
        if row is not None and self.window.move_history_step(row, row + by):
            self.refresh()
            self.steps.setCurrentRow(row + by)

    def remove(self) -> None:
        row = self._row()
        if row is not None:
            self.window.remove_history_step(row)
            self.refresh()


class HistoryActions:
    """Mixed into MeshWindow through ExpertActions."""

    HISTORY_STARTED = "From now on, every change is kept in the history (Modify > History)."
    HISTORY_STOPPED = "The history is no longer kept. The parts stay as they are."
    STEP_FIXED = "That step has no settings to change. It can be skipped, moved or removed."
    FORMULA_ENDED = "That setting no longer follows a formula."
    STEP_NEEDS_PARTS = "Select the parts to use the step on, then choose the step again."
    STEP_NAMES_ITS_PARTS = ("That step was used on a clicked face or on a part it names, so it can't "
                            "be used on the selected parts instead.")
    NO_PARAMETERS = "There are no parameters yet: Modify > Change Parameters."

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
            for index, (number, step) in enumerate(zip(numbers or range(1, len(steps) + 1), steps)):
                if step.get("off"):
                    done.append(copy.deepcopy(step))  # kept as it was, ready to be used again
                    continue
                try:
                    step = {**step, "call": self._worked_call(step["call"], known)}
                    effect = self._replay_step(scratch, step, warned)
                    parameters.apply_links(scratch.scene.shapes, known)
                except (history.HistoryError, parameters.ParameterError) as exc:
                    reason = exc
                    faces = getattr(getattr(self, (step["call"] or {}).get("method", ""), None), "replay_faces", ())
                    if history.made_later(step, steps[index + 1:], {s.id for s in scratch.scene.shapes}, faces):
                        reason = history.MADE_LATER
                    raise history.HistoryError(
                        f"Step {number} ({history.describe(step)}) can't be worked out: {reason}"
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

    def _worked_call(self, call, known: dict):
        """`call` with the settings its formulas give, worked out from the
        parameters' values `known` through the tool's own form."""
        if call is None or not call.get("formulas"):
            return call
        found = editors().get(call["method"])
        if found is None:
            return call
        _title, fields_of, back = found
        fields = fields_of(call["args"])
        values = {f[0]: f[2] for f in fields}
        values.update(history.formula_values(fields, call["formulas"], known))
        worked = copy.deepcopy(call)
        worked["args"].update(history.plain(back(values, call["args"])))
        return worked

    def _replay_step(self, scratch, step, warned) -> dict:
        """Do one step again on `scratch`; what it changed this time."""
        scene = scratch.scene
        call = step["call"]
        if call is None:
            history.apply_changes(scene, step["effect"] or {})
            return copy.deepcopy(step["effect"])
        method = getattr(self, call["method"], None)
        known = {s.id for s in scene.shapes}
        faces = getattr(method, "replay_faces", ())
        if method is None or (not faces and any(i not in known for i in call["picked"])):
            raise history.HistoryError(history.USED_GONE)
        # A tool used on a clicked face is told its part; what else was
        # selected then doesn't matter, and may not be there yet.
        scene.select([i for i in call["picked"] if i in known])
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

    def change_history_step(self, index: int, settings: dict, ended=()) -> bool:
        """Give step `index` (from 0) new settings and work the project out
        again. The formulas of the form fields `ended` end: those settings
        stay as typed."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps) or steps[index]["call"] is None:
            return False
        call = steps[index]["call"]
        call["args"].update(history.plain(settings))
        formulas = {k: v for k, v in call.get("formulas", {}).items() if k not in ended}
        call.pop("formulas", None)
        if formulas:
            call["formulas"] = formulas
        if not self._rework("Cannot change the step", "change a step", steps):
            return False
        if ended:
            self.statusBar().showMessage(self.FORMULA_ENDED)
        return True

    def step_formulas(self, index: int):
        """(form title, fields) for typing step `index`'s numbers as
        formulas: one text box per number of the tool's form, holding its
        formula or its number. None if it has no settings to change."""
        editor = self.step_editor(index)
        if editor is None:
            return None
        title, fields, _back = editor
        formulas = self.history_steps()[index]["call"].get("formulas", {})
        return title, [(key, label, formulas.get(key, f"{value:g}"), {})
                       for key, label, value, _options in history.number_fields(fields)]

    def set_step_formulas(self, index: int, texts: dict) -> bool:
        """Give step `index` (from 0) the numbers and formulas `texts` (form
        field -> text) and work the project out again. A text that uses a
        parameter becomes a formula; one that doesn't is a number."""
        editor = self.step_editor(index)
        if editor is None:
            return False
        _title, fields, back = editor
        steps = copy.deepcopy(self.history_steps())
        call = steps[index]["call"]
        by_key = {f[0]: f for f in history.number_fields(fields)}
        values = {f[0]: f[2] for f in fields}
        formulas = dict(call.get("formulas", {}))
        try:
            known = parameters.values(self.document.scene.parameters)
            for key, text in texts.items():
                if key not in by_key:
                    continue
                text = str(text).strip()
                if parameters.names_in(text):
                    formulas[key] = text
                else:
                    formulas.pop(key, None)
                    values[key] = history.checked_number(by_key[key], parameters.evaluate(text, {}))
            values.update(history.formula_values(fields, formulas, known))
        except parameters.ParameterError as exc:
            self._warn("Cannot use these formulas", str(exc))
            return False
        call["args"].update(history.plain(back(values)))
        call.pop("formulas", None)
        if formulas:
            call["formulas"] = formulas
        return self._rework("Cannot use these formulas", "use parameters in a step", steps)

    def ask_step_formulas(self, index: int) -> bool:
        found = self.step_formulas(index)
        if found is None:
            self.statusBar().showMessage(self.STEP_FIXED)
            return False
        if not self.document.scene.parameters:
            self.statusBar().showMessage(self.NO_PARAMETERS)
            return False
        title, fields = found
        values = run_form(self, f"Use Parameters in {title}", fields, note=FORMULAS_NOTE)
        return values is not None and self.set_step_formulas(index, values)

    def remove_history_step(self, index: int) -> bool:
        """Take step `index` (from 0) out and work the project out again."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps):
            return False
        del steps[index]
        numbers = [n for n in range(1, len(steps) + 2) if n != index + 1]
        return self._rework("Cannot remove the step", "remove a step", steps, numbers=numbers)

    def skip_history_step(self, index: int, skip: bool = True) -> bool:
        """Skip step `index` (from 0), or use it again, and work the
        project out again."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps) or bool(steps[index].get("off")) == bool(skip):
            return False
        if skip:
            steps[index]["off"] = True
        else:
            steps[index].pop("off", None)
        return self._rework("Cannot skip the step" if skip else "Cannot use the step again",
                            "skip a step" if skip else "use a step again", steps)

    def move_history_step(self, index: int, to: int) -> bool:
        """Move step `index` (from 0) to place `to` and work the project
        out again."""
        steps = copy.deepcopy(self.history_steps())
        if not (0 <= index < len(steps) and 0 <= to < len(steps)) or index == to:
            return False
        numbers = list(range(1, len(steps) + 1))
        steps.insert(to, steps.pop(index))
        numbers.insert(to, numbers.pop(index))
        return self._rework("Cannot move the step", "move a step", steps, numbers=numbers)

    def retarget_history_step(self, index: int, ids) -> bool:
        """Use step `index` (from 0), a tool used on the selection, on the
        parts `ids` instead, and work the project out again."""
        steps = copy.deepcopy(self.history_steps())
        if not 0 <= index < len(steps) or steps[index]["call"] is None:
            return False
        call = steps[index]["call"]
        if getattr(getattr(self, call["method"], None), "replay_faces", ()) or \
                any(key.endswith(("_id", "ids")) for key in call["args"]):
            self.statusBar().showMessage(self.STEP_NAMES_ITS_PARTS)
            return False
        ids = list(ids)
        if not ids:
            self.statusBar().showMessage(self.STEP_NEEDS_PARTS)
            return False
        if ids == call["picked"]:
            return False
        call["picked"] = ids
        return self._rework("Cannot use the step on those parts", "use a step on other parts", steps)

    def step_sketch(self, index: int):
        """(shape id, its name, the curves) when step `index` drew one
        sketch or changed one sketch's curves (or those of a part made from
        one), else None."""
        steps = self.history_steps()
        if not 0 <= index < len(steps) or steps[index]["call"] is not None:
            return None
        effect = steps[index]["effect"] or {}
        drawn = [(d["id"], d.get("name", ""), d["params"]["entities"]) for d in effect.get("added", [])
                 if isinstance(d.get("params", {}).get("entities"), list)]
        changed = [(i, d.get("name", ""), d["params"]["entities"]) for i, d in effect.get("changed", {}).items()
                   if isinstance(d.get("params", {}).get("entities"), list)]
        if len(drawn) + len(changed) != 1 or (drawn and len(effect.get("added", [])) != 1):
            return None
        shape_id, name, entities = (drawn or changed)[0]
        return shape_id, name or next(iter(effect.get("names", [])), "the sketch"), entities

    def change_sketch_step(self, index: int, entities) -> bool:
        """Give the sketch step `index` (see step_sketch) new curves and work
        the project out again. Refused if a part made from them would not
        come out solid, or a later step no longer works."""
        found = self.step_sketch(index)
        if found is None:
            return False
        shape_id = found[0]
        title = "Cannot change the sketch"
        try:
            entities = sketch.clean_entities(entities)
        except sketch.SketchError as exc:
            self._warn(title, str(exc))
            return False
        steps = copy.deepcopy(self.history_steps())
        effect = steps[index]["effect"]
        for data in effect.get("added", []):
            data["params"]["entities"] = entities
        if shape_id in effect.get("changed", {}):
            effect["changed"][shape_id]["params"]["entities"] = entities
        try:
            scene = self._replayed(steps)
            # The part (or sketch) itself must still come out.
            if shape_id in {s.id for s in scene.shapes}:
                shape_geometry(scene.get(shape_id), scene.fit_clearances)
        except history.HistoryError as exc:
            self._warn(title, str(exc))
            return False
        except (BuildError, sketch.SketchError) as exc:
            self._warn(title, f"Step {index + 1} ({history.describe(steps[index])}) can't be worked out: {exc}")
            return False
        self._replace_scene("change a sketch step", scene)
        return True

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
        drawn = self.step_sketch(index) if editor is None else None
        if drawn is not None:
            from mesh import sketch_editor

            _shape_id, name, entities = drawn
            entities = sketch_editor.edit_sketch(self, f"Change {name}", entities, note=SKETCH_STEP_NOTE)
            return entities is not None and self.change_sketch_step(index, entities)
        if editor is None:
            self.statusBar().showMessage(self.STEP_FIXED)
            return False
        title, fields, back = editor
        values = run_form(self, f"Change {title}", fields, note=STEP_NOTE)
        if values is None:
            return False
        # A setting given by a formula, typed over, no longer follows it.
        shown = {key: round(value, int((options or {}).get("decimals", 2))) if isinstance(value, float) else value
                 for key, _label, value, options in fields}
        formulas = self.history_steps()[index]["call"].get("formulas", {})
        ended = [key for key in formulas if values.get(key) != shown.get(key)]
        return self.change_history_step(index, back(values), ended)

    def do_history(self) -> None:
        dialog = HistoryDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
