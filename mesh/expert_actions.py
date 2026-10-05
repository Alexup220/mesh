"""The window's Expert mode actions: the Sketch and Create menus.

Create's patterns and Mirror are in mesh.pattern_actions, the Modify menu
in mesh.modify_actions (its parameters in mesh.parameter_actions, its
history list in mesh.history_actions), the Assemble menu in
mesh.component_actions, the
Construct menu in mesh.construct_actions and the Inspect menu in
mesh.inspect_actions; all are mixed in here.

MeshWindow inherits these, so they share its document, undo and click
tools. Each tool's geometry lives in a core module (mesh.sketch,
mesh.create); this is only the wiring: ask, try, then snapshot and apply
on success.
"""

from PySide6.QtCore import QTimer

from mesh import coils, construct, create, features, modify, sketch, sketch_editor, threads
from mesh.component_actions import ComponentActions
from mesh.construct_actions import ConstructActions
from mesh.history import replayable
from mesh.history_actions import HistoryActions
from mesh.inspect_actions import InspectActions
from mesh.modify_actions import ModifyActions
from mesh.parameter_actions import ParameterActions
from mesh.pattern_actions import PatternActions
from mesh.panels import run_form
from mesh.shapes import is_reference

# What a tool makes from a sketch: a new solid part, or a Hole that cuts
# the parts it is grouped with (Solid/Hole + Group, as everywhere in mesh).
RESULTS = [("part", "A new part"), ("hole", "A hole (cuts parts when grouped with them)")]


def _result_fields(sketches: int = 1):
    keep = "Keep the sketch as well" if sketches == 1 else "Keep the sketches as well"
    return [
        ("result", "Make", "part", {"choices": RESULTS}),
        ("keep_sketch", keep, False, {}),
    ]


def extrude_results(part: str) -> list:
    """What Extrude can do with a part selected with the sketch, as Fusion's
    Join, Cut and Intersect do (by mesh.modify.combine's ways)."""
    return [
        ("union", f"Joined to {part}"),
        ("difference", f"Cut out of {part}"),
        ("intersection", f"Only where it overlaps {part}"),
    ]


def extrude_fields(plane: str | None = None, part: str | None = None):
    """The Extrude form's fields; with the name of a construction plane
    selected with the sketch, a choice to extrude up to it, and with the
    name of a part, choices to join to it, cut from it or keep the overlap."""
    slope = {"min": -features.TAPER_LIMIT, "max": features.TAPER_LIMIT}
    extent = []
    if plane is not None:
        extent = [("extent", "How far", "plane", {"choices": [
            ("distance", "The distance typed below"),
            ("plane", f"Up to {plane} (parallel to the sketch)"),
        ]})]
    result = _result_fields()
    if part is not None:
        result[0] = ("result", "Make", "union", {"choices": extrude_results(part) + RESULTS})
    return extent + [
        ("distance", "Distance (mm)", 20.0, {"min": 0.1, "max": 10000.0}),
        ("side", "Direction", "one", {"choices": features.SIDES}),
        ("taper", "Sides slope in (degrees)", 0.0, slope),
    ] + result


EXTRUDE_NOTE = (
    "Pushes the sketch's closed outlines straight out of its plane. A sketch on a face faces "
    "out of the part: for a hole into that face, choose \"The other way\". With a slope, every "
    f"side leans in by that angle going away from the sketch (out, for less than 0; at most "
    f"{features.TAPER_LIMIT:g} degrees), and the corners stay sharp."
)

EXTRUDE_TO_PLANE_NOTE = (
    " Up to a plane: the plane must be parallel to the sketch, and the distance and which way "
    "are worked out from where it is now. They stay numbers in the Details panel, so moving the "
    "plane later does not move the end."
)

EXTRUDE_WITH_PART_NOTE = (
    " With a part: the extrusion can be joined to it, cut out of it, or kept only where they "
    "overlap, as Modify > Combine does. The result is a group, and Ungroup gives the part and "
    "the extrusion back."
)


def ask_extrude(parent, plane: str | None = None, part: str | None = None) -> dict | None:
    note = (EXTRUDE_NOTE + (EXTRUDE_TO_PLANE_NOTE if plane is not None else "")
            + (EXTRUDE_WITH_PART_NOTE if part is not None else ""))
    return run_form(parent, "Extrude", extrude_fields(plane, part), note=note)


def revolve_fields(axes):
    return [
        ("axis", "Turn around", axes[0][0], {"choices": axes}),
        ("angle", "Angle (degrees)", 360.0, {"min": 0.1, "max": 360.0}),
    ] + _result_fields()


def ask_revolve(parent, axes) -> dict | None:
    return run_form(
        parent, "Revolve", revolve_fields(axes),
        note="Turns the sketch's closed outlines around a line, like a part on a lathe. "
             "The outline must lie all on one side of the line. Round surfaces are made "
             "of narrow flat strips, like a cylinder's.",
    )


def sweep_shape_fields():
    """How a sweep's outline changes along its path."""
    low, high = features.END_SCALE_LIMITS
    return [
        ("twist", "Twist along the path (degrees)", 0.0,
         {"min": -features.TWIST_LIMIT, "max": features.TWIST_LIMIT}),
        ("end_scale", "Size at the far end (%)", 100.0, {"min": low, "max": high}),
    ]


def sweep_fields(sketches, path_id: str):
    return [
        ("path", "Path to follow", path_id, {"choices": [(s.id, s.name) for s in sketches]}),
    ] + sweep_shape_fields() + _result_fields(len(sketches))


SWEEP_NOTE = (
    "Carries the other sketch's closed outlines along the path, square to it. If the outline is "
    "not drawn across an end of the path, it is moved to the nearer end. Curved paths are "
    "followed in short straight steps. A twist turns the outline round the path as it goes (more "
    "than 0 turns like a screw going along the path), and the size at the far end shrinks or "
    "grows it towards the path; both change evenly along its length. On a closed path the twist "
    "must be whole turns and the size can't change."
)


def ask_sweep(parent, sketches, path_id: str) -> dict | None:
    return run_form(parent, "Sweep", sweep_fields(sketches, path_id), note=SWEEP_NOTE)


def loft_fields(count: int):
    return [
        ("sides", "Sides between the outlines", "straight", {"choices": features.LOFT_SIDES}),
    ] + _result_fields(count)


def ask_loft(parent, sketches) -> dict | None:
    order = ", ".join(s.name for s in sketches)
    return run_form(
        parent, "Loft", loft_fields(len(sketches)),
        note=f"Joins the sketches' outlines with a skin, in the order you picked them: {order}. "
             "Each sketch needs one closed outline with no holes. The sides run straight from "
             "one outline to the next, or along a smooth curve through all of them (with three "
             "or more outlines; with two, both are the same). Smooth sides are made of narrow "
             "flat strips, like a cylinder's. A construction point picked first or last closes "
             "the loft to that point, where the point is now.",
    )


def thread_fields(height: float, pitch: float):
    return [
        ("standard", "Thread sizes", "metric", {"choices": threads.STANDARDS}),
        ("pitch", "Thread pitch (mm per turn)", float(pitch), {"min": 0.2, "max": 100.0, "step": 0.05}),
        ("per_inch", "Threads per inch, for inch or pipe (0 for the standard count)", 0.0,
         {"min": 0.0, "max": 200.0, "decimals": 1}),
        ("length", "Threaded length (mm)", float(height), {"min": 0.1, "max": 10000.0}),
        ("end", "Thread starts", "top", {"choices": threads.ENDS}),
        ("hand", "Thread turns", "right", {"choices": threads.HANDS}),
        ("starts", "Starts (threads side by side)", 1, {"min": 1, "max": threads.MAX_STARTS}),
        ("lead_in", "Starting end of the thread", "none", {"choices": threads.LEAD_INS}),
    ]


def thread_note(standard: str, pitch: float, inch: tuple | None = None, pipe: tuple | None = None) -> str:
    nearest = ""
    if inch is not None and pipe is not None:
        nearest = (f" The nearest inch size is {inch[0]} UNC ({inch[1]} threads per inch), and the "
                   f"nearest British pipe size G {pipe[0]} ({pipe[1]} threads per inch).")
    return (f"Puts a screw thread on the cylinder; its diameter is the thread's full size. The "
            f"nearest metric size is {standard}, whose pitch ({pitch:g} mm) is filled in.{nearest} On a "
            "cylinder Hole it makes a threaded hole: with a fit chosen, a thread of the same size "
            "screws into it. With more than one start, that many threads run side by side: the "
            "pitch is still from one ridge to the next, and a nut goes that many times further "
            "in each turn. Inch (UNC) threads have the metric shape; British pipe (G) threads "
            "are straight, not tapered, with the pipe thread's round tips made of short flat "
            "pieces. Both take the threads per inch, or 0 for the standard count of the size "
            "nearest the cylinder's diameter (which stays as it is). A bevelled end slopes at 45 "
            "degrees: a thread down to its root, a threaded hole out to its full size, so they "
            "start into each other easily.")


def coil_fields():
    d = coils.DEFAULTS
    return [
        ("diameter", "Diameter across the outside (mm)", d["diameter"], {"min": 0.5, "max": 10000.0}),
        ("pitch", "Pitch (mm per turn)", d["pitch"], {"min": 0.1, "max": 10000.0, "step": 0.5}),
        ("turns", "Turns", d["turns"], {"min": 0.05, "max": float(coils.MAX_TURNS), "step": 0.5}),
        ("wire", "Wire thickness (mm)", d["wire"], {"min": 0.1, "max": 1000.0, "step": 0.5}),
        ("wire_shape", "Wire shape", d["wire_shape"], {"choices": coils.WIRE_SHAPES}),
        ("winding", "Coil winds", d["winding"], {"choices": coils.WINDINGS}),
        ("result", "Make", "part", {"choices": RESULTS}),
    ]


COIL_NOTE = (
    "Makes a coil spring standing on the workplane: a round or square wire wound round an "
    "upright line. The pitch is how far it rises in each turn, and must be more than the wire's "
    "thickness so the turns don't touch. The wire's outline is drawn through the middle line and "
    "carried round, so the ends are cut square across the wire there. Each turn is made of 48 "
    "short straight pieces, and a round wire's outline has 24 sides."
)


def ask_coil(parent) -> dict | None:
    return run_form(parent, "Coil", coil_fields(), note=COIL_NOTE)


def ask_thread(parent, height: float, standard: str, pitch: float, inch: tuple | None = None,
               pipe: tuple | None = None) -> dict | None:
    return run_form(parent, "Thread", thread_fields(height, pitch), note=thread_note(standard, pitch, inch, pipe))


class ExpertActions(ModifyActions, PatternActions, ConstructActions, InspectActions, ParameterActions,
                    HistoryActions, ComponentActions):
    """Mixed into MeshWindow (see mesh.expert for the menu items)."""

    # The click-on-a-part tools Expert mode adds; turning the mode off
    # stops any of them that is waiting for a click.
    EXPERT_CLICK_TOOLS = (
        ("sketch_face",) + ModifyActions.MODIFY_CLICK_TOOLS + PatternActions.PATTERN_CLICK_TOOLS
        + ConstructActions.CONSTRUCT_CLICK_TOOLS + InspectActions.INSPECT_CLICK_TOOLS
    )

    EXPERT_TOOL_PROMPTS = {
        "sketch_face": "Click a flat face of a part to sketch on it. Esc cancels.",
        **ModifyActions.MODIFY_TOOL_PROMPTS,
        **PatternActions.PATTERN_TOOL_PROMPTS,
        **ConstructActions.CONSTRUCT_TOOL_PROMPTS,
        **InspectActions.INSPECT_TOOL_PROMPTS,
    }

    # The method each of those tools' clicks goes to: (part id, triangle
    # clicked, world point).
    EXPERT_CLICK_HANDLERS = {
        "sketch_face": "_sketch_face_picked",
        **ModifyActions.MODIFY_CLICK_HANDLERS,
        **PatternActions.PATTERN_CLICK_HANDLERS,
        **ConstructActions.CONSTRUCT_CLICK_HANDLERS,
        **InspectActions.INSPECT_CLICK_HANDLERS,
    }

    # The later prompts of the tools that take several clicks.
    _STAGED = {**ConstructActions._STAGED, **InspectActions.INSPECT_STAGED}

    # --- Sketches ------------------------------------------------------------------

    def add_sketch(self, entities, frame, name: str | None = None) -> bool:
        """Add a sketch of `entities` on the plane `frame` places. One undo
        step. Not through add_shape: a sketch stays on its own plane, even
        while Place on a Face waits to place the next new part."""
        scene = self.document.scene
        shape = self._attempt(
            "Cannot make the sketch",
            lambda: create.new_sketch(entities, frame, name or create.next_sketch_name(scene.shapes)),
        )
        if shape is None:
            return False
        self.document.snapshot("add sketch")
        scene.add(shape)
        scene.select([shape.id])
        self.sync()
        return True

    def do_new_sketch(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) == 1 and construct.is_guide(chosen[0], "plane"):
            # Drawn straight onto the selected construction plane.
            origin, normal = construct.plane_of(chosen[0])
            entities = sketch_editor.edit_sketch(self, f"New sketch on {chosen[0].name}")
            if entities is not None:
                self.add_sketch(entities, sketch.plane_frame(normal, origin))
            return
        choice = sketch_editor.ask_sketch_plane(self)
        if choice is None:
            return
        frame = sketch.named_plane_frame(choice["plane"], choice["distance"])
        entities = sketch_editor.edit_sketch(
            self, "New sketch", note=sketch_editor.PLANE_NOTES[choice["plane"]]
        )
        if entities is not None:
            self.add_sketch(entities, frame)

    def do_sketch_on_face(self) -> None:
        if not any(not is_reference(s) for s in self.document.scene.shapes):
            self.statusBar().showMessage("Add a part first, then sketch on one of its flat faces.")
            return
        self.start_tool("sketch_face")

    def _sketch_face_picked(self, shape_id: str, face_index: int, _point=None) -> None:
        """Nothing changes until the sketch window's OK, so a click takes no
        undo step."""
        scene = self.document.scene
        try:
            shape = scene.get(shape_id)
            frame, outlines = create.face_plane(shape, face_index, scene.fit_clearances)
        except (KeyError, IndexError, ValueError):
            self.statusBar().showMessage(self.TOOL_PROMPTS["sketch_face"])
            return
        self._clear_tool()
        self.sync()
        # Opened once the click is over: a window opened during the click
        # would leave the 3D view thinking the button is still held down.
        QTimer.singleShot(0, lambda: self.sketch_on_face(frame, outlines, shape.name))

    def sketch_on_face(self, frame, outlines, part_name: str) -> bool:
        self.viewport.end_drag()
        entities = sketch_editor.edit_sketch(
            self, f"Sketch on a face of {part_name}", guides=outlines,
            note="The face's outline is shown dashed.",
        )
        return entities is not None and self.add_sketch(entities, frame)

    def _chosen_sketch(self, what: str = "use it"):
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.is_sketch(chosen[0]):
            self.statusBar().showMessage(f"Select one sketch to {what}.")
            return None
        return chosen[0]

    CHANGE_SKETCH_HINT = "Select one sketch, or one part made from a sketch, to change its curves."

    LOFT_NOT_REDRAWN = "A loft's outlines can't be changed. Undo the loft, change the sketches, and loft again."

    def do_edit_sketch(self) -> None:
        chosen = self.document.scene.selected()
        if len(chosen) != 1 or not create.has_sketch(chosen[0]):
            loft = len(chosen) == 1 and chosen[0].params.get("primitive") == "loft"
            self.statusBar().showMessage(self.LOFT_NOT_REDRAWN if loft else self.CHANGE_SKETCH_HINT)
            return
        shape = chosen[0]
        entities = create.sketch_entities(shape)
        while True:
            entities = sketch_editor.edit_sketch(self, f"Change {shape.name}", entities)
            if entities is None:
                return
            changed = self._changed_sketch(shape, entities)
            if changed is not None:
                self._apply_sketch_change(shape, changed)
                return
            # Refused (and said why): back to the sketch window with the
            # curves as they were left, to fix them.

    def _changed_sketch(self, shape, entities):
        return self._attempt(
            "Cannot change the sketch",
            lambda: create.with_entities(shape, entities, self.document.scene.fit_clearances),
        )

    def _apply_sketch_change(self, shape, changed) -> bool:
        if changed.params == shape.params:
            return False
        self.document.snapshot("change sketch")
        shape.params = changed.params
        shape.transform = changed.transform
        self.sync()
        return True

    def set_sketch_entities(self, shape, entities) -> bool:
        """Give a sketch, or a part made from one, new curves. One undo
        step; none if nothing changed or the part would not come out solid."""
        changed = self._changed_sketch(shape, entities)
        return changed is not None and self._apply_sketch_change(shape, changed)

    # --- Solids from sketches -----------------------------------------------------

    def _add_from_sketches(self, label: str, sources, shape, keep_sketch: bool) -> None:
        """One undo step: add the new part and, unless kept, remove the
        sketches it was made from (it keeps a copy of their curves)."""
        scene = self.document.scene
        self.document.snapshot(label)
        if not keep_sketch:
            scene.remove([s.id for s in sources])
        scene.add(shape)
        scene.select([shape.id])
        self.sync()

    EXTRUDE_HINT = "Select one sketch to extrude."
    EXTRUDE_EXTRAS = ("Select one sketch to extrude, and if you like one construction plane to "
                      "extrude up to and one part to join it to or cut it from.")
    NO_PLANE = "Select a construction plane with the sketch to extrude up to it."
    NO_PART = "Select a part with the sketch to join the extrusion to it or cut it from it."

    def _extrude_selection(self):
        """(the selected sketch, the construction plane selected with it or
        None, the part selected with it or None), or None and a message."""
        chosen = self._picked()
        sketches = [s for s in chosen if create.is_sketch(s)]
        planes = [s for s in chosen if construct.is_guide(s, "plane")]
        parts = [s for s in chosen if not is_reference(s)]
        if len(sketches) != 1:
            self.statusBar().showMessage(self.EXTRUDE_HINT)
            return None
        if len(planes) > 1 or len(parts) > 1 or len(chosen) > 1 + len(planes) + len(parts):
            self.statusBar().showMessage(self.EXTRUDE_EXTRAS)
            return None
        return sketches[0], (planes[0] if planes else None), (parts[0] if parts else None)

    @replayable()
    def extrude_selected(self, distance: float, side: str = "one", hole: bool = False,
                         keep_sketch: bool = False, taper: float = 0.0, to_plane: bool = False,
                         combine: str | None = None) -> bool:
        """Extrude the selected sketch `distance` mm (or, with `to_plane`, up
        to the construction plane selected with it). With `combine` (a way
        of mesh.modify.combine), the extrusion is joined to the part
        selected with it, cut out of it, or kept where they overlap. One
        undo step."""
        chosen = self._extrude_selection()
        if chosen is None:
            return False
        source, plane, part = chosen
        if to_plane and plane is None:
            self.statusBar().showMessage(self.NO_PLANE)
            return False
        if combine is not None and part is None:
            self.statusBar().showMessage(self.NO_PART)
            return False
        scene = self.document.scene

        def build():
            far, way = create.distance_to_plane(source, plane) if to_plane else (distance, side)
            made = create.make_extrude(source, far, way, hole and combine is None, taper)
            if combine is None:
                return made
            return modify.combine(part, [made], combine, False, scene.fit_clearances)

        shape = self._attempt("Cannot extrude", build)
        if shape is None:
            return False
        if combine is None:
            self._add_from_sketches("extrude", [source], shape, keep_sketch)
            return True
        self.document.snapshot("extrude")
        scene.remove([part.id] + ([] if keep_sketch else [source.id]))
        scene.add(shape)
        scene.select([shape.id])
        self.sync()
        return True

    @replayable()
    def revolve_selected(self, axis: str = "y", angle: float = 360.0, hole: bool = False,
                         keep_sketch: bool = False) -> bool:
        source = self._chosen_sketch("revolve")
        if source is None:
            return False
        shape = self._attempt("Cannot revolve",
                              lambda: create.make_revolve(source, axis, angle, hole))
        if shape is None:
            return False
        self._add_from_sketches("revolve", [source], shape, keep_sketch)
        return True

    def do_revolve(self) -> None:
        source = self._chosen_sketch("revolve")
        if source is None:
            return
        values = ask_revolve(self, create.revolve_axes(source))
        if values is not None:
            self.revolve_selected(values["axis"], values["angle"], values["result"] == "hole",
                                  values["keep_sketch"])

    TWO_SKETCHES_HINT = "Select two sketches: the outline, and the path to sweep it along."

    def _picked(self):
        """The selected shapes in the order they were picked."""
        scene = self.document.scene
        order = {shape_id: index for index, shape_id in enumerate(scene.selection)}
        return sorted(scene.selected(), key=lambda s: order[s.id])

    def _two_sketches(self):
        chosen = self._picked()
        if len(chosen) != 2 or not all(create.is_sketch(s) for s in chosen):
            self.statusBar().showMessage(self.TWO_SKETCHES_HINT)
            return None
        return chosen

    @replayable()
    def sweep_selected(self, path_id: str | None = None, hole: bool = False,
                       keep_sketch: bool = False, twist: float = 0.0, end_scale: float = 100.0) -> bool:
        """Sweep one selected sketch's outline along the other's path
        (`path_id`, or the likelier one), turning it `twist` degrees and
        changing its size to `end_scale` percent by the far end."""
        pair = self._two_sketches()
        if pair is None:
            return False
        path = next((s for s in pair if s.id == path_id), None) or create.likely_path(*pair)
        outline = pair[1] if path is pair[0] else pair[0]
        shape = self._attempt("Cannot sweep", lambda: create.make_sweep(outline, path, hole, twist, end_scale))
        if shape is None:
            return False
        self._add_from_sketches("sweep", pair, shape, keep_sketch)
        return True

    def do_sweep(self) -> None:
        pair = self._two_sketches()
        if pair is None:
            return
        values = ask_sweep(self, pair, create.likely_path(*pair).id)
        if values is not None:
            self.sweep_selected(values["path"], values["result"] == "hole", values["keep_sketch"],
                                values.get("twist", 0.0), values.get("end_scale", 100.0))

    LOFT_HINT = create.LOFT_PICKS

    def _sketches_in_order(self):
        """The selected sketches in the order picked, perhaps with a
        construction point first or last; or None and a hint."""
        chosen = self._picked()
        if not create.loft_picks_fit(chosen):
            self.statusBar().showMessage(self.LOFT_HINT)
            return None
        return chosen

    @replayable()
    def loft_selected(self, hole: bool = False, keep_sketch: bool = False, sides: str = "straight") -> bool:
        """Loft the selected sketches in the order picked, with straight or
        smooth sides (features.LOFT_SIDES)."""
        sketches = self._sketches_in_order()
        if sketches is None:
            return False
        shape = self._attempt("Cannot loft", lambda: create.make_loft(sketches, hole, sides))
        if shape is None:
            return False
        # A construction point it closes to stays, as guides do.
        self._add_from_sketches("loft", [s for s in sketches if create.is_sketch(s)], shape, keep_sketch)
        return True

    def do_loft(self) -> None:
        sketches = self._sketches_in_order()
        if sketches is None:
            return
        values = ask_loft(self, sketches)
        if values is not None:
            self.loft_selected(values["result"] == "hole", values["keep_sketch"],
                               values.get("sides", "straight"))

    def do_extrude(self) -> None:
        chosen = self._extrude_selection()
        if chosen is None:
            return
        _source, plane, part = chosen
        extra = {key: shape.name for key, shape in (("plane", plane), ("part", part)) if shape is not None}
        values = ask_extrude(self, **extra)
        if values is not None:
            result = values["result"]
            self.extrude_selected(values["distance"], values["side"], result == "hole",
                                  values["keep_sketch"], values.get("taper", 0.0),
                                  values.get("extent") == "plane",
                                  result if result in modify.COMBINE_OPS else None)

    # --- Thread ----------------------------------------------------------------------

    def _thread_target(self):
        """The one selected cylinder, or None (and a message)."""
        chosen = [s for s in self._picked() if not is_reference(s)]
        if len(chosen) != 1 or chosen[0].kind != "primitive" or chosen[0].params.get("primitive") != "cylinder":
            tube = len(chosen) == 1 and chosen[0].kind == "primitive" and chosen[0].params.get("primitive") == "tube"
            self.statusBar().showMessage(create.TUBE_THREAD if tube else create.NOT_A_CYLINDER)
            return None
        return chosen[0]

    @replayable()
    def thread_selected(self, pitch: float, length: float, end: str = "top", hand: str = "right",
                        starts: int = 1, standard: str = "metric", per_inch: float = 0.0,
                        lead_in: str = "none") -> bool:
        """Put a thread on the selected cylinder, with `starts` threads side
        by side: metric with `pitch`, or inch or pipe with `per_inch`
        threads to an inch, its starting end cut square or bevelled
        (`lead_in`). One undo step on success."""
        shape = self._thread_target()
        if shape is None:
            return False
        scene = self.document.scene
        changed = self._attempt("Cannot add the thread", lambda: create.threaded(
            shape, pitch, length, end, hand, scene.fit_clearances, starts, standard, per_inch, lead_in))
        if changed is None:
            return False
        self.document.snapshot("thread")
        shape.params = changed.params
        self.sync()
        return True

    # --- Coil ------------------------------------------------------------------------

    @replayable()
    def add_coil(self, diameter: float = 20.0, pitch: float = 5.0, turns: float = 5.0, wire: float = 2.0,
                 wire_shape: str = "round", winding: str = "right", hole: bool = False) -> bool:
        """Add a coil (see mesh.coils) and select it. One undo step on
        success."""
        shape = self._attempt("Cannot make the coil", lambda: create.make_coil(
            diameter, pitch, turns, wire, wire_shape, winding, hole))
        if shape is None:
            return False
        self.document.snapshot("coil")
        self.document.scene.add(shape)
        self.document.scene.select([shape.id])
        self.sync()
        return True

    def do_coil(self) -> None:
        values = ask_coil(self)
        if values is not None:
            self.add_coil(values["diameter"], values["pitch"], values["turns"], values["wire"],
                          values["wire_shape"], values["winding"], values["result"] == "hole")

    def do_thread(self) -> None:
        shape = self._thread_target()
        if shape is None:
            return
        standard, pitch = create.thread_choice(shape)
        diameter = float(shape.params.get("diameter", 20.0))
        values = ask_thread(self, float(shape.params.get("height", 20.0)), standard, pitch,
                            inch=threads.inch_size(diameter), pipe=threads.pipe_size(diameter))
        if values is not None:
            self.thread_selected(values["pitch"], values["length"], values["end"], values["hand"],
                                 values.get("starts", 1), values.get("standard", "metric"),
                                 values.get("per_inch", 0.0), values.get("lead_in", "none"))
