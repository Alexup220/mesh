"""Preferences that belong to this computer, not to a project.

Kept in a small JSON file in the user's config folder
($XDG_CONFIG_HOME/mesh/settings.json, normally ~/.config/mesh/). Nothing
here is ever written into a .mesh project, so opening a project never
changes a preference and a preference never changes a project.

Every preference starts at its default when the file is missing, damaged
or holds something unexpected. Expert mode in particular is on only when
the file says exactly `true`.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from mesh.themes import DEFAULT_THEME

FILE_NAME = "settings.json"


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "mesh" / FILE_NAME


@dataclass
class Settings:
    # Show the larger set of modeling tools (see mesh.expert). Off on a
    # fresh install.
    expert_mode: bool = False
    # The window's colour theme, by name (see mesh.themes). An unknown name
    # falls back to the default theme when the window starts.
    theme: str = DEFAULT_THEME
    # Where the window's panels were docked and how big it was, as Qt
    # wrote it (base64 text). Empty until the window is first closed, which
    # is also how the window knows to show its welcome screen.
    layout: str = ""
    # Where save() writes. None keeps the settings in memory only, which is
    # what a window built without settings (as in the tests) gets.
    path: Path | None = field(default=None, compare=False, repr=False)

    @classmethod
    def load(cls, path) -> "Settings":
        settings = cls(path=Path(path))
        try:
            raw = json.loads(settings.path.read_text())
        except (OSError, ValueError):
            return settings
        if isinstance(raw, dict):
            settings.expert_mode = raw.get("expert_mode") is True
            if isinstance(raw.get("theme"), str) and raw["theme"].strip():
                settings.theme = raw["theme"].strip()
            if isinstance(raw.get("layout"), str):
                settings.layout = raw["layout"]
        return settings

    def _to_dict(self) -> dict:
        # The theme and layout are written only once they differ from a
        # fresh install's, so a file that never had them stays as it was.
        raw = {"expert_mode": bool(self.expert_mode)}
        if self.theme != DEFAULT_THEME:
            raw["theme"] = str(self.theme)
        if self.layout:
            raw["layout"] = str(self.layout)
        return raw

    def save(self) -> bool:
        """Write the settings to `path`. Returns False, changing nothing on
        disk, when there is no path or the file can't be written."""
        if self.path is None:
            return False
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(self._to_dict(), indent=2))
            os.replace(temporary, self.path)
        except OSError:
            return False
        return True
