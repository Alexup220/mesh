"""Colour themes for the window: six built in, plus any the user saves.

A theme is a name and one colour (lowercase #rrggbb) for each of TOKENS.
The built-in themes live here; a custom theme is a small JSON file in the
user's config folder ($XDG_CONFIG_HOME/mesh/themes/, normally
~/.config/mesh/themes/), one file per theme:

    {"name": "My theme", "colors": {"background": "#23262b", ...}}

Nothing here is ever written into a project. A damaged or incomplete theme
file is skipped, never half-applied.
"""

import json
import os
import re
from pathlib import Path

# What every theme sets. The window derives hover and pressed shades from
# these, so a theme is never more than these eight colours.
TOKENS: tuple[str, ...] = (
    "background",  # behind everything
    "panel",       # panels, the ribbon, the status bar
    "text",
    "accent",      # the active tool, focus, the chosen tab
    "border",
    "viewport",    # behind the 3D view
    "grid",        # the workplane grid
    "selection",   # the selected part's outline
)

TOKEN_LABELS: dict[str, str] = {
    "background": "Background",
    "panel": "Panels",
    "text": "Text",
    "accent": "Highlight",
    "border": "Borders",
    "viewport": "3D view background",
    "grid": "Grid",
    "selection": "Selected part",
}

DEFAULT_THEME = "Dark"

BUILTIN: dict[str, dict[str, str]] = {
    "Dark": {
        "background": "#23262b", "panel": "#1b1e22", "text": "#e6e8ea",
        "accent": "#4a90d9", "border": "#3d434b", "viewport": "#292b33",
        "grid": "#80878f", "selection": "#ffd933",
    },
    "Light": {
        "background": "#f3f4f6", "panel": "#ffffff", "text": "#1f2328",
        "accent": "#1f6feb", "border": "#c9ced6", "viewport": "#e8ebef",
        "grid": "#9aa3ad", "selection": "#e8590c",
    },
    "Fusion Grey": {
        "background": "#3c3f41", "panel": "#2f3133", "text": "#dcdcdc",
        "accent": "#f28c28", "border": "#55585b", "viewport": "#9ea3a8",
        "grid": "#6f7478", "selection": "#2f8fd8",
    },
    "Midnight Blue": {
        "background": "#141b2d", "panel": "#0d1323", "text": "#d6def0",
        "accent": "#5ea1ff", "border": "#26314d", "viewport": "#101828",
        "grid": "#3c4a6b", "selection": "#ffcc4d",
    },
    "High Contrast": {
        "background": "#000000", "panel": "#000000", "text": "#ffffff",
        "accent": "#ffff00", "border": "#ffffff", "viewport": "#000000",
        "grid": "#00ffff", "selection": "#ff00ff",
    },
    "Solarized": {
        "background": "#002b36", "panel": "#073642", "text": "#eee8d5",
        "accent": "#268bd2", "border": "#30535c", "viewport": "#073642",
        "grid": "#586e75", "selection": "#b58900",
    },
}

MAX_NAME = 40
_COLOR = re.compile(r"^#[0-9a-f]{6}$")


class ThemeError(ValueError):
    """A theme that can't be saved, in plain words."""


def themes_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "mesh" / "themes"


def clean_color(value) -> str | None:
    """`value` as lowercase #rrggbb, or None if it isn't a colour like that."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _COLOR.match(value) else None


def clean_colors(colors) -> dict[str, str] | None:
    """Every token's colour, or None if any is missing or not a colour."""
    if not isinstance(colors, dict):
        return None
    out = {}
    for token in TOKENS:
        color = clean_color(colors.get(token))
        if color is None:
            return None
        out[token] = color
    return out


def file_name(name: str) -> str:
    """The file a custom theme called `name` is saved in."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "theme") + ".json"


def load_custom(directory=None) -> dict[str, dict[str, str]]:
    """The saved custom themes, by name, skipping any damaged file and any
    that reuses a built-in theme's name."""
    folder = Path(directory) if directory is not None else themes_dir()
    found: dict[str, dict[str, str]] = {}
    try:
        paths = sorted(folder.glob("*.json"))
    except OSError:
        return found
    for path in paths:
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        colors = clean_colors(raw.get("colors"))
        if not isinstance(name, str) or not name.strip() or colors is None:
            continue
        name = name.strip()[:MAX_NAME]
        if name in BUILTIN:
            continue
        found[name] = colors
    return found


def all_themes(directory=None) -> dict[str, dict[str, str]]:
    """Built-in themes first, then the custom ones."""
    return {**BUILTIN, **load_custom(directory)}


def save_custom(name: str, colors: dict, directory=None) -> Path:
    """Save a custom theme. Raises ThemeError, writing nothing, if the name
    is empty, too long or a built-in theme's, or a colour is not #rrggbb."""
    name = (name or "").strip()
    if not name:
        raise ThemeError("Give the theme a name.")
    if len(name) > MAX_NAME:
        raise ThemeError(f"Keep the name under {MAX_NAME} characters.")
    if name in BUILTIN:
        raise ThemeError(f"{name} is one of the built-in themes. Choose another name.")
    cleaned = clean_colors(colors)
    if cleaned is None:
        raise ThemeError("Every colour must be written like #1a2b3c.")
    folder = Path(directory) if directory is not None else themes_dir()
    path = folder / file_name(name)
    temporary = path.with_name(path.name + ".tmp")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"name": name, "colors": cleaned}, indent=2))
        os.replace(temporary, path)
    except OSError as exc:
        raise ThemeError(f"The theme could not be saved: {exc.strerror or exc}.") from exc
    return path
