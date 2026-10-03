"""Text as a solid: letter outlines from a bundled font, pushed up into 3D.

The font (DejaVu Sans, mesh/fonts/, with its licence) ships with mesh and is
read with fontTools, so text comes out identical on every machine. System
fonts are never looked at.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

from mesh.solids import from_manifold, m3

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"

# Straight pieces per curved piece of a letter outline. Plenty for letters
# a few millimetres tall; more only adds triangles.
CURVE_STEPS = 8


class _FlatteningPen(BasePen):
    """Collects glyph outlines as closed polygons, curves cut into lines."""

    def __init__(self, glyph_set) -> None:
        super().__init__(glyph_set)
        self.contours: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []

    def _moveTo(self, pt):
        self._current = [pt]

    def _lineTo(self, pt):
        self._current.append(pt)

    def _qCurveToOne(self, pt1, pt2):
        p0 = np.asarray(self._getCurrentPoint(), dtype=float)
        p1, p2 = np.asarray(pt1, dtype=float), np.asarray(pt2, dtype=float)
        for t in np.linspace(0.0, 1.0, CURVE_STEPS + 1)[1:]:
            point = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2
            self._current.append((float(point[0]), float(point[1])))

    def _curveToOne(self, pt1, pt2, pt3):
        p0 = np.asarray(self._getCurrentPoint(), dtype=float)
        p1, p2, p3 = (np.asarray(p, dtype=float) for p in (pt1, pt2, pt3))
        for t in np.linspace(0.0, 1.0, CURVE_STEPS + 1)[1:]:
            point = ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
                     + 3 * (1 - t) * t**2 * p2 + t**3 * p3)
            self._current.append((float(point[0]), float(point[1])))

    def _closePath(self):
        if len(self._current) >= 3:
            self.contours.append(self._current)
        self._current = []

    _endPath = _closePath


@lru_cache(maxsize=1)
def _font():
    font = TTFont(str(FONT_PATH))
    glyphs = font.getGlyphSet()
    bounds = BoundsPen(glyphs)
    glyphs["H"].draw(bounds)
    cap_height = bounds.bounds[3]
    return font, glyphs, font.getBestCmap(), cap_height


def outline(text: str) -> tuple[list[list[tuple[float, float]]], float]:
    """Letter outlines for one line of text, in font units, plus the cap
    height (the height of a capital H) to scale by."""
    font, glyphs, cmap, cap_height = _font()
    advances = font["hmtx"].metrics
    pen = _FlatteningPen(glyphs)
    x = 0.0
    for char in text:
        # A character the font does not have shows as its "missing" box
        # rather than vanishing silently.
        name = cmap.get(ord(char), ".notdef")
        glyphs[name].draw(TransformPen(pen, (1, 0, 0, 1, x, 0)))
        x += advances[name][0]
    return pen.contours, cap_height


def text_mesh(text: str, letter_height: float, depth: float, clearance: float = 0.0) -> trimesh.Trimesh:
    """One line of text as a solid: `letter_height` mm is the height of a
    capital letter, `depth` mm how far the letters stand up. Centred on
    X/Y, resting on Z = 0. `clearance` > 0 grows every letter outward by
    that much on every side (for engraved text with a fit)."""
    if not text.strip():
        raise ValueError("text needs at least one visible character")
    contours, cap_height = outline(text)
    scale = float(letter_height) / cap_height
    polygons = [np.asarray(c, dtype=np.float64) * scale for c in contours]
    shape = m3.CrossSection(polygons, m3.FillRule.NonZero)
    if clearance > 0.0:
        shape = shape.offset(clearance, m3.JoinType.Round)
    low_x, low_y, high_x, high_y = shape.bounds()
    shape = shape.translate((-(low_x + high_x) / 2.0, -(low_y + high_y) / 2.0))
    solid = m3.Manifold.extrude(shape, float(depth) + 2.0 * clearance)
    return from_manifold(solid.translate((0.0, 0.0, -clearance)))
