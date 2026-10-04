"""Is this model actually printable, and will it fit on the bed?

Shown permanently in the status bar. The message strings are user-facing
and deliberately avoid modeling jargon.
"""

from dataclasses import dataclass

import numpy as np

from mesh.ops import HasGapsError, NothingLeftError, NothingToCombineError, evaluate
from mesh.scene import Scene
from mesh.shapes import is_reference, shape_geometry


@dataclass
class Report:
    empty: bool
    watertight: bool
    size_mm: tuple[float, float, float]
    volume_mm3: float
    fits: bool
    message: str


_cache: dict = {"key": None, "report": None}


def check(scene: Scene, revision: object = None) -> Report:
    """Evaluate printability, in this Report.

    `evaluate()` runs a full manifold boolean over every visible shape --
    real work, not something to redo on every keystroke of an unrelated
    edit. When the caller passes a `revision` (mesh.scene.Document.revision
    changes exactly when the scene's contents change), the last Report for
    that revision is reused instead of recomputing. Pass nothing (as the
    tests below do, working directly on a bare Scene with no Document) and
    it always recomputes -- there's nothing to key a cache on.
    """
    if revision is not None:
        key = (id(scene), revision)
        if _cache["key"] == key:
            return _cache["report"]

    report = _check(scene)

    if revision is not None:
        _cache["key"] = key
        _cache["report"] = report
    return report


def _check(scene: Scene) -> Report:
    visible = [s for s in scene.shapes if s.visible]
    try:
        result = evaluate(visible, clearances=scene.fit_clearances)
    except HasGapsError:
        # A part that isn't closed can't be combined with the rest; say so
        # with the overall size rather than fail.
        bounds = np.array([shape_geometry(s, scene.fit_clearances).bounds
                           for s in visible if not is_reference(s)])
        size = tuple(float(v) for v in bounds[:, 1].max(axis=0) - bounds[:, 0].min(axis=0))
        return Report(
            empty=False,
            watertight=False,
            size_mm=size,
            volume_mm3=0.0,
            fits=all(s <= b for s, b in zip(size, scene.build_volume)),
            message=(
                f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm — this model has gaps "
                "and may not print correctly."
            ),
        )
    except NothingToCombineError as exc:
        if isinstance(exc, NothingLeftError):
            message = "The holes cut away everything — nothing is left to print."
        else:
            message = "Nothing to print yet — add a shape."
        return Report(
            empty=True,
            watertight=True,
            size_mm=(0.0, 0.0, 0.0),
            volume_mm3=0.0,
            fits=True,
            message=message,
        )

    size = tuple(float(v) for v in (result.bounds[1] - result.bounds[0]))
    fits = all(s <= b for s, b in zip(size, scene.build_volume))
    solid = bool(result.is_watertight)

    if not fits:
        message = (
            f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm — too big for your printer "
            f"({scene.build_volume[0]:.0f} x {scene.build_volume[1]:.0f} x {scene.build_volume[2]:.0f} mm)."
        )
    elif not solid:
        message = (
            f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm — this model has gaps "
            "and may not print correctly."
        )
    else:
        message = f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm — ready to print."

    return Report(
        empty=False,
        watertight=solid,
        size_mm=size,
        volume_mm3=float(result.volume),
        fits=fits,
        message=message,
    )
