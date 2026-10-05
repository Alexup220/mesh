"""Copies in a pattern, and mirrored copies: Expert mode's patterns and Mirror.

Every function returns new shapes (copies with new ids, as Duplicate makes)
and leaves the shapes passed in alone; the window adds them in one undo
step. Copies keep their part's name, size numbers, Solid/Hole and fit, so a
patterned Hole still cuts once grouped. Sketches are guides: they are never
copied here, and a sketch can be the path or the mirror plane. A request
that can't be met raises BuildError with a plain message.

    rectangular  rows and columns along two directions: the world's, or a
                 construction axis's
    circular     round a line through a point, along one of the world's
                 directions (Repeat in a Circle, extended: any of the three
                 lines, several parts at once, and the parts stay where
                 they are), or round a construction axis (circular_about)
    along_path   along the one path a sketch draws, keeping the parts'
                 place relative to the path's start, and optionally turning
                 with it (along_edge: along a part's run of edges instead,
                 when it lies flat in one plane)
    mirrored     reflected across a plane: a sketch's, a flat face's, or one
                 of the middle planes through 0 (mirrored_into_one also
                 joins each image to its part, as Combine's Join does)

Rows and Around a Line can also go both ways from the parts (symmetric),
and every pattern can leave out copies by their number (the parts are 1).

All exact: copies are the same shapes moved, turned or reflected. Along a
curved path the copies sit on the path's straight pieces (64 per circle).
"""

import math
from dataclasses import dataclass

import numpy as np

from mesh import create, edges, sketch
from mesh.builders import GUIDES_ARE_NOT_PARTS, MAX_COPIES, BuildError, _check_count, _copy
from mesh.modify import MOVE_LIMIT, _bounds, combine, flat_face
from mesh.ops import AXES, _canonical
from mesh.shapes import is_reference, shape_geometry

PARTS_ONLY = "Select the parts to copy. Sketches are guides, so they are not copied."
SMOOTH_DEGREES = 10.0  # a path turning less than this between pieces is a curve, not a corner


def _parts(shapes) -> list:
    parts = [s for s in shapes if not is_reference(s)]
    if not parts:
        raise BuildError(PARTS_ONLY)
    return parts


def _check_total(positions: int, parts: list) -> None:
    if (positions - 1) * len(parts) > MAX_COPIES:
        raise BuildError(f"That is too many copies. Try {MAX_COPIES} or fewer in all.")


def _moved(parts: list, matrix: np.ndarray, canonical: bool = True) -> list:
    """Copies of `parts`, each moved by the world transform `matrix`."""
    out = []
    for part in parts:
        clone = _copy(part)
        moved = matrix @ np.asarray(part.transform, dtype=np.float64)
        clone.transform = _canonical(moved) if canonical else moved
        out.append(clone)
    return out


def _distance(value: float, what: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value == 0.0:
        raise BuildError(f"The {what} must be a distance other than 0 mm.")
    if abs(value) > MOVE_LIMIT:
        raise BuildError(f"The {what} can be at most {MOVE_LIMIT:g} mm.")
    return value


# --- Leaving copies out -------------------------------------------------------------

LEAVE_OUT_HINT = "Type the numbers of the copies to leave out, such as 3, 5 or 7-9."


def copy_numbers(text) -> list[int]:
    """The copy numbers typed as text ("3, 5, 7-9"), or given as a list of
    numbers already. Nothing typed means none."""
    if isinstance(text, (list, tuple)):
        try:
            return sorted({int(v) for v in text})
        except (TypeError, ValueError) as exc:
            raise BuildError(LEAVE_OUT_HINT) from exc
    numbers = set()
    for piece in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        if not piece:
            continue
        low, dash, high = piece.partition("-")
        try:
            first = int(low)
            last = int(high) if dash else first
        except ValueError as exc:
            raise BuildError(LEAVE_OUT_HINT) from exc
        if last < first or last - first > MAX_COPIES:
            raise BuildError(LEAVE_OUT_HINT)
        numbers.update(range(first, last + 1))
    return sorted(numbers)


def _left_out(skip, total: int) -> set[int]:
    """The numbers in `skip`, checked against a pattern of `total` (the
    parts are number 1)."""
    numbers = set(copy_numbers(skip))
    if 1 in numbers:
        raise BuildError("Number 1 is the parts themselves, so it can't be left out.")
    beyond = [n for n in sorted(numbers) if not 2 <= n <= total]
    if beyond:
        raise BuildError(f"The pattern has {total} in all, so there is no number {beyond[0]} to leave out.")
    if len(numbers) >= total - 1:
        raise BuildError("That would leave out every copy.")
    return numbers


def _steps(count: int, symmetric: bool) -> list[int]:
    """How many steps from the parts each place in a row is, in the order
    they are numbered: the parts, then one way, then (both ways) the other."""
    return list(range(count)) + ([-i for i in range(1, count)] if symmetric else [])


# --- Rectangular --------------------------------------------------------------------


def _direction(axis) -> np.ndarray:
    """A row's direction: one of the world's ("x", "y", "z"), or any
    direction given as three numbers (a construction axis's, say)."""
    if isinstance(axis, str):
        if axis not in AXES:
            raise ValueError(f"unknown direction {axis!r}")
        out = np.zeros(3)
        out[AXES[axis]] = 1.0
        return out
    out = np.asarray([float(v) for v in axis], dtype=np.float64)
    length = float(np.linalg.norm(out)) if out.shape == (3,) else 0.0
    if not math.isfinite(length) or length < 1e-9:
        raise BuildError("The direction for the rows has no length.")
    return out / length


def rectangular(shapes, count: int, spacing: float, axis="x", count2: int = 1,
                spacing2: float = 10.0, axis2="y", extent: bool = False,
                symmetric: bool = False, skip=()) -> list:
    """Copies of the parts in rows along `axis` (`count` in a row,
    `spacing` mm apart, less than 0 going the other way) and, with `count2`
    more than 1, columns along `axis2`. A direction is "x", "y", "z" or
    three numbers. Counts include the originals.

    With `extent`, each spacing is the whole length from the parts to the
    last copy instead of the gap from one to the next. With `symmetric`,
    each row (and column) goes the same again the other way from the parts.
    `skip` lists the numbers of copies to leave out: the parts are 1, then
    along the first row (the other way after, both ways), row by row."""
    parts = _parts(shapes)
    first_way, second_way = _direction(axis), _direction(axis2)
    count, count2 = int(count), int(count2)
    if count < 1 or count2 < 1:
        raise BuildError("Each direction needs at least 1 in a row.")
    along, across = _steps(count, symmetric), _steps(count2, symmetric)
    total = len(along) * len(across)
    _check_count(total)
    _check_total(total, parts)
    first = _distance(spacing, "spacing") if count > 1 else 0.0
    second = _distance(spacing2, "spacing") if count2 > 1 else 0.0
    if extent:
        first, second = first / max(count - 1, 1), second / max(count2 - 1, 1)
    if count > 1 and count2 > 1 and np.linalg.norm(np.cross(first_way, second_way)) < 1e-9:
        raise BuildError("Choose two different directions for the rows and the columns.")
    left_out = _left_out(skip, total)
    step, step2 = first * first_way, second * second_way
    out = []
    number = 0
    for j in across:
        for i in along:
            number += 1
            if (i == 0 and j == 0) or number in left_out:
                continue
            matrix = np.eye(4)
            matrix[:3, 3] = i * step + j * step2
            out += _moved(parts, matrix, canonical=False)
    return out


# --- Circular -----------------------------------------------------------------------


def circular(shapes, count: int, axis: str = "z", centre=(0.0, 0.0, 0.0), angle: float = 360.0,
             symmetric: bool = False, skip=()) -> list:
    """Copies of the parts turned round the line along `axis` through
    `centre`, anticlockwise seen from the line's positive end. A full 360
    degrees spaces them evenly all the way round; a smaller angle puts the
    first and last exactly that far apart. The parts stay where they are,
    and `count` includes them. With `symmetric`, the same again the other
    way round (the count and the angle each way); `skip` as rectangular,
    numbered round from the parts."""
    if axis not in AXES:
        raise ValueError(f"unknown direction {axis!r}")
    direction = np.zeros(3)
    direction[AXES[axis]] = 1.0
    return circular_about(shapes, count, centre, direction, angle, symmetric, skip)


def circular_about(shapes, count: int, point, direction, angle: float = 360.0,
                   symmetric: bool = False, skip=()) -> list:
    """As circular, round the line through `point` along `direction` (a
    construction axis, say), anticlockwise seen from its tip."""
    parts = _parts(shapes)
    count = _check_count(count)
    turns = _steps(count, symmetric)
    _check_count(len(turns))
    _check_total(len(turns), parts)
    angle = float(angle)
    if not math.isfinite(angle) or not 0.0 < angle <= 360.0:
        raise BuildError("The angle must be more than 0 and at most 360 degrees.")
    if symmetric and angle >= 180.0:
        raise BuildError("Both ways, the angle each way must be less than 180 degrees, so the two "
                         "sides don't meet.")
    centre = np.asarray([float(v) for v in point], dtype=np.float64)
    if centre.shape != (3,) or not np.isfinite(centre).all():
        raise BuildError("Type ordinary numbers for the centre.")
    left_out = _left_out(skip, len(turns))
    k = np.asarray(direction, dtype=np.float64)
    k = k / np.linalg.norm(k)
    full = angle >= 360.0 - 1e-9
    step = angle / count if full else angle / (count - 1)
    out = []
    for number, i in enumerate(turns, 1):
        if i == 0 or number in left_out:
            continue
        a = math.radians(i * step)
        cross = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
        turn = np.eye(3) * math.cos(a) + math.sin(a) * cross + (1.0 - math.cos(a)) * np.outer(k, k)
        matrix = np.eye(4)
        matrix[:3, :3] = turn
        matrix[:3, 3] = centre - turn @ centre
        out += _moved(parts, matrix)
    return out


# --- Along a path -------------------------------------------------------------------


@dataclass
class _Path:
    """A sketch's path in its own plane, starting where the copies start."""

    points: np.ndarray    # (N, 2), no repeated points; closed paths don't repeat the first
    closed: bool
    starts: np.ndarray    # distance along the path where each straight piece starts
    lengths: np.ndarray   # each piece's length
    headings: np.ndarray  # each piece's direction, as an angle (radians)

    @property
    def length(self) -> float:
        return float(self.lengths.sum())

    def piece(self, s: float) -> int:
        k = int(np.searchsorted(self.starts, s, side="right")) - 1
        return min(max(k, 0), len(self.lengths) - 1)

    def point(self, s: float) -> np.ndarray:
        k = self.piece(s)
        a, b = self.points[k], self.points[(k + 1) % len(self.points)]
        f = 0.0 if self.lengths[k] == 0.0 else (s - self.starts[k]) / self.lengths[k]
        return a + min(max(f, 0.0), 1.0) * (b - a)

    def heading(self, s: float) -> float:
        """The path's direction at `s`: along a curve, turned smoothly from
        one straight piece's middle to the next; at a corner, the piece's own."""
        k = self.piece(s)
        middle = self.starts[k] + self.lengths[k] / 2.0
        pieces = len(self.lengths)
        other = k - 1 if s < middle else k + 1
        if not self.closed and not 0 <= other < pieces:
            return float(self.headings[k])
        o = other % pieces
        turn = math.remainder(float(self.headings[o] - self.headings[k]), 2.0 * math.pi)
        if abs(turn) > math.radians(SMOOTH_DEGREES):
            return float(self.headings[k])
        gap = (self.lengths[k] + self.lengths[o]) / 2.0
        return float(self.headings[k] + turn * abs(s - middle) / gap)


def _path(guide, near) -> tuple[_Path, np.ndarray]:
    """The sketch `guide`'s path in its plane, starting at the end nearest
    `near` (a world point), or round a closed path at the point nearest it;
    and the sketch's plane (its transform)."""
    if not create.is_sketch(guide):
        raise BuildError("Select the parts and one sketch whose curves make the path.")
    try:
        points, closed = sketch.single_path(guide.params["entities"])
    except sketch.SketchError as exc:
        raise BuildError(str(exc)) from exc
    return _path_through(points, closed, np.asarray(guide.transform, dtype=np.float64), near)


def _path_through(points, closed: bool, frame, near) -> tuple[_Path, np.ndarray]:
    """The path through `points` (in the plane `frame` places), starting
    at the end nearest `near` (a world point), or round a closed path at
    the point nearest it; and that plane."""
    points = np.asarray(points, dtype=np.float64)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9])
    points = points[keep]
    if closed and len(points) > 1 and np.linalg.norm(points[0] - points[-1]) < 1e-9:
        points = points[:-1]
    if len(points) < (3 if closed else 2):
        raise BuildError("The path is too short to put copies along.")
    frame = np.asarray(frame, dtype=np.float64)
    target = (np.linalg.inv(frame) @ np.append(np.asarray(near, dtype=np.float64), 1.0))[:2]
    if not closed:
        if np.linalg.norm(points[-1] - target) < np.linalg.norm(points[0] - target):
            points = points[::-1].copy()
    else:
        ends = np.roll(points, -1, axis=0)
        along = ends - points
        f = np.clip(np.einsum("ij,ij->i", target - points, along) / np.einsum("ij,ij->i", along, along), 0.0, 1.0)
        nearest = points + f[:, None] * along
        k = int(np.argmin(np.linalg.norm(nearest - target, axis=1)))
        m = len(points)
        if f[k] <= 1e-9:
            order = [points[(k + j) % m] for j in range(m)]
        elif f[k] >= 1.0 - 1e-9:
            order = [points[(k + 1 + j) % m] for j in range(m)]
        else:  # part way along a piece: start there, and end back there
            order = [nearest[k]] + [points[(k + 1 + j) % m] for j in range(m)]
        points = np.array(order)
    ends = np.roll(points, -1, axis=0) if closed else points[1:]
    along = ends - points[: len(ends)]
    lengths = np.linalg.norm(along, axis=1)
    starts = np.concatenate([[0.0], np.cumsum(lengths)[:-1]])
    headings = np.unwrap(np.arctan2(along[:, 1], along[:, 0]))
    return _Path(points, closed, starts, lengths, headings), frame


def along_path(shapes, guide, count: int, spacing: float | None = None, follow: bool = False,
               skip=()) -> list:
    """Copies of the parts along the sketch `guide`'s path, from the end
    nearest them (round a closed path, from the point nearest them):
    `spacing` mm apart along it, or spread evenly over the whole path for
    None. Each copy keeps the parts' place relative to the path's start;
    with `follow`, it also turns as the path turns. `count` includes the
    originals; `skip` lists copies to leave out, numbered along the path
    from the parts (1)."""
    parts = _parts(shapes)
    count = _check_count(count)
    _check_total(count, parts)
    left_out = _left_out(skip, count)
    path, frame = _path(guide, _bounds(parts).mean(axis=0))
    return _along(parts, path, frame, count, spacing, follow, left_out)


EDGE_NOT_FLAT = (
    "That edge doesn't lie flat in one plane, so copies can't go along it. Draw the path in a "
    "sketch instead."
)


def edge_path(part, face_index: int, point, clearances: dict | None = None):
    """The run of edges next to a click on `part` (the edge nearest the
    click and those it runs on into smoothly, as Round an Edge finds them)
    as a path in the plane it lies flat in: (its points in that plane,
    whether it goes all the way round, the plane as a 4x4 frame). Refused
    if it doesn't lie flat in one plane."""
    if is_reference(part):
        raise BuildError("Click a face of a part next to the edge, not a sketch or guide.")
    tm = shape_geometry(part, clearances)
    run = edges.find_run(tm, face_index, point)
    points = tm.vertices[run.vertices]
    middle = points.mean(axis=0)
    facing = tm.face_normals[face_index]
    if len(points) == 2:
        normal = facing  # a straight edge lies in the face clicked
    else:
        normal = np.linalg.svd(points - middle)[2][2]
        size = max(1.0, float(np.ptp(points, axis=0).max()))
        if np.abs((points - middle) @ normal).max() > 1e-6 * size:
            raise BuildError(EDGE_NOT_FLAT)
        if normal @ facing < 0.0:
            normal = -normal
    frame = sketch.plane_frame(normal, middle)
    return sketch.to_sketch(frame, points), bool(run.closed), frame


def along_edge(shapes, part, face_index: int, point, count: int, spacing: float | None = None,
               follow: bool = False, skip=(), clearances: dict | None = None) -> list:
    """Copies of the parts along a run of edges of `part` next to a click
    (see edge_path), as along_path makes them along a sketch's path."""
    parts = _parts(shapes)
    count = _check_count(count)
    _check_total(count, parts)
    left_out = _left_out(skip, count)
    points, closed, plane = edge_path(part, face_index, point, clearances)
    path, frame = _path_through(points, closed, plane, _bounds(parts).mean(axis=0))
    return _along(parts, path, frame, count, spacing, follow, left_out)


def _along(parts, path: _Path, frame, count: int, spacing, follow: bool, left_out) -> list:
    """The copies of along_path, along `path` in the plane `frame`."""
    total = path.length
    if spacing is None:
        spacing = total / (count if path.closed else count - 1)
    else:
        spacing = float(spacing)
        if not math.isfinite(spacing) or spacing <= 0.0:
            raise BuildError("The spacing must be more than 0 mm.")
        reach = spacing * (count - 1)
        if reach > total + 1e-6 or (path.closed and reach > total - spacing + 1e-6):
            raise BuildError(
                f"The copies don't fit along the path, which is {total:.1f} mm long. Use fewer "
                "copies, a smaller spacing, or spread them evenly."
            )
    p0, h0 = path.point(0.0), path.heading(0.0)
    back = np.linalg.inv(frame)
    out = []
    for i in range(1, count):
        if i + 1 in left_out:
            continue
        s = i * spacing
        local = np.eye(4)
        if follow:
            turn = path.heading(s) - h0
            c, sn = math.cos(turn), math.sin(turn)
            local[:2, :2] = [[c, -sn], [sn, c]]
        local[:2, 3] = path.point(s) - local[:2, :2] @ p0
        out += _moved(parts, frame @ local @ back)
    return out


# --- Mirror -------------------------------------------------------------------------

MIDDLE_PLANES = ("x", "y", "z")


def mirrored(shapes, origin, normal) -> list:
    """Copies of the parts reflected across the plane through `origin`
    facing `normal`, named "(mirrored)"."""
    if any(is_reference(s) for s in shapes):
        raise BuildError(GUIDES_ARE_NOT_PARTS.format(tool="Mirror"))
    if not shapes:
        raise BuildError("Select the parts to mirror first.")
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    p = np.asarray(origin, dtype=np.float64)
    matrix = np.eye(4)
    matrix[:3, :3] -= 2.0 * np.outer(n, n)
    matrix[:3, 3] = 2.0 * float(p @ n) * n
    out = _moved(list(shapes), matrix, canonical=False)
    for clone in out:
        clone.name = f"{clone.name} (mirrored)"
    return out


def mirrored_into_one(shapes, origin, normal) -> list:
    """Each part joined with its mirror image across the plane into one
    part, as Combine's Join joins two parts: a group per part, which
    Ungroup takes apart into the part and its image. The image need not
    touch the part. Holes are refused: joined, a Hole's fit could no
    longer be added exactly."""
    holes = [s for s in shapes if s.is_hole and not is_reference(s)]
    if holes:
        raise BuildError(
            f"Joining a mirror image to its part works on solid parts, and {holes[0].name} is a "
            "Hole. Mirror it as a separate copy, or group it with its part first."
        )
    joined = []
    for part, image in zip(shapes, mirrored(shapes, origin, normal)):
        group = combine(part, [image], "union")
        group.name = f"{part.name} (mirrored, joined)"
        joined.append(group)
    return joined


def plane_of_sketch(guide) -> tuple[np.ndarray, np.ndarray]:
    frame = np.asarray(guide.transform, dtype=np.float64)
    return frame[:3, 3].copy(), frame[:3, 2] / np.linalg.norm(frame[:3, 2])


def plane_of_face(shape, face_index: int, clearances: dict | None = None):
    face = flat_face(shape, face_index, clearances)
    return face.centre, face.normal


def middle_plane(axis: str) -> tuple[np.ndarray, np.ndarray]:
    """The plane through 0 that `axis` runs square to (x: the upright plane
    between left and right)."""
    normal = np.zeros(3)
    normal[AXES[axis]] = 1.0
    return np.zeros(3), normal
