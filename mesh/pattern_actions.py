"""The window's Expert mode patterns (in the Create menu).

Mixed into MeshWindow through ExpertActions. The geometry is in
mesh.patterns; this is only the wiring: ask, try, then snapshot and add the
copies on success, as one undo step.
"""

from mesh import patterns
from mesh.builders import MAX_COPIES
from mesh.modify import MOVE_LIMIT
from mesh.panels import run_form
from mesh.shapes import is_reference

DIRECTIONS = [("x", "Left / right"), ("y", "Forward / back"), ("z", "Up / down")]


def rectangular_fields():
    spacing = {"min": -MOVE_LIMIT, "max": MOVE_LIMIT}
    return [
        ("count", "How many in a row", 3, {"min": 1, "max": MAX_COPIES}),
        ("spacing", "Spacing along a row (mm)", 30.0, spacing),
        ("axis", "Each row goes", "x", {"choices": DIRECTIONS}),
        ("count2", "How many rows", 1, {"min": 1, "max": MAX_COPIES}),
        ("spacing2", "Spacing between rows (mm)", 30.0, spacing),
        ("axis2", "The next rows go", "y", {"choices": DIRECTIONS}),
    ]


RECTANGULAR_NOTE = (
    "Copies the selected parts in a row, and in more rows if you like. The counts include the "
    "parts themselves. Spacing is from one copy to the next; less than 0 goes the other way."
)


def ask_rectangular(parent) -> dict | None:
    return run_form(parent, "Pattern in Rows", rectangular_fields(), note=RECTANGULAR_NOTE)


class PatternActions:
    """Mixed into MeshWindow through ExpertActions."""

    PATTERN_CLICK_TOOLS = ()
    PATTERN_TOOL_PROMPTS = {}
    PATTERN_CLICK_HANDLERS = {}

    PATTERN_HINT = "Select the parts to copy first."

    def _pattern_parts(self):
        """The selected parts in pick order; None (and a message) if only
        sketches or nothing are selected."""
        parts = [s for s in self._picked() if not is_reference(s)]
        if not parts:
            self.statusBar().showMessage(self.PATTERN_HINT)
            return None
        return parts

    def _add_pattern(self, label: str, parts, build) -> bool:
        """Add the copies `build` makes, with the parts, as one undo step;
        none if it refuses."""
        copies = self._attempt("Cannot make the copies", build)
        if copies is None:
            return False
        self.document.snapshot(label)
        for clone in copies:
            self.document.scene.add(clone)
        self.document.scene.select([s.id for s in parts] + [c.id for c in copies])
        self.sync()
        return True

    # --- In rows ------------------------------------------------------------------

    def rectangular_pattern_selected(self, count: int = 3, spacing: float = 30.0, axis: str = "x",
                                     count2: int = 1, spacing2: float = 30.0, axis2: str = "y") -> bool:
        parts = self._pattern_parts()
        if parts is None:
            return False
        return self._add_pattern(
            "pattern in rows", parts,
            lambda: patterns.rectangular(parts, count, spacing, axis, count2, spacing2, axis2),
        )

    def do_rectangular_pattern(self) -> None:
        if self._pattern_parts() is None:
            return
        values = ask_rectangular(self)
        if values is not None:
            self.rectangular_pattern_selected(**values)
