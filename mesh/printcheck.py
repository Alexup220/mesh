"""Is this model actually printable, and will it fit on the bed?

Shown permanently in the status bar. The message strings are user-facing
and deliberately avoid modeling jargon.
"""

from dataclasses import dataclass

from mesh.ops import NothingToCombineError, evaluate
from mesh.scene import Scene


@dataclass
class Report:
    empty: bool
    watertight: bool
    size_mm: tuple[float, float, float]
    volume_mm3: float
    fits: bool
    message: str


def check(scene: Scene) -> Report:
    visible = [s for s in scene.shapes if s.visible]
    try:
        result = evaluate(visible)
    except NothingToCombineError:
        return Report(
            empty=True,
            watertight=True,
            size_mm=(0.0, 0.0, 0.0),
            volume_mm3=0.0,
            fits=True,
            message="Nothing to print yet — add a shape.",
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
