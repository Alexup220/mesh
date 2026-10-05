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

FILE_NAME = "settings.json"


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "mesh" / FILE_NAME


@dataclass
class Settings:
    # Show the larger set of modeling tools (see mesh.expert). Off on a
    # fresh install.
    expert_mode: bool = False
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
        return settings

    def save(self) -> bool:
        """Write the settings to `path`. Returns False, changing nothing on
        disk, when there is no path or the file can't be written."""
        if self.path is None:
            return False
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"expert_mode": bool(self.expert_mode)}, indent=2))
            os.replace(temporary, self.path)
        except OSError:
            return False
        return True
