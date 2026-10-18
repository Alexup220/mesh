"""Generate printable Kirito & Asuna (Inner Anime "Kirito & Asuna Rings") as STL.

Each ring is a watertight height field over the band: the outer radius is
r(theta, z) = inner radius + wall - edge rounding - relief + stone. The relief
is a set of chisel cuts traced from the shop photos: every crease of the real
ring is a crisp step with a ramp that rises back to the band surface on one
side, so the blades read as layered facets; thin lines are V grooves.

Relief coordinates are (s, zeta): s = arc length in mm on the outer surface
from the stone centre, +s to the right when you look at the stone with the +z
rim on top; zeta = z / (half the front band width). The pattern keeps its size
in mm at any ring size, like the real (one size, adjustable) ring.

Print axis is Z (ring lies flat), -z rim on the bed. On the closed band no
downward-facing slope is steeper than 45 degrees, so no supports are needed;
the *_open variant adds one bridged slot (see open_back_cutter).

Usage (needs numpy and trimesh; the *_open variant also needs manifold3d):
    python3 make_rings.py                       # default sizes
    python3 make_rings.py --kirito-id 18.9 --asuna-id 14.9
"""
import argparse
import importlib.util
import pathlib

import numpy as np
import trimesh

FIT = 0.2            # added to the inner diameter to offset FDM shrink / elephant foot
INNER_CHAMFER = 0.3  # comfort chamfer on the inner edges
GRID = 0.05          # mesh spacing on the outer surface (mm)
# The real ring is open: at the back the band splits into an upper and a lower strip that
# overlap from BACK_UPPER (where the upper strip ends, a step in the top rim) round to
# BACK_LOWER (where the lower strip ends). Angles in radians from the stone, through +theta.
BACK_UPPER = np.radians(133)
BACK_LOWER = np.radians(190)
SPLIT_GAP = 0.4      # *_open: vertical clearance between the two strips (2 layers at 0.2 mm)
END_GAP = 1.0        # *_open: clearance at each strip end (mm)
WEB = 0.4            # *_open: breakaway web that holds the upper strip while printing (mm)


def line(path, ramp_dir, depth=0.3, ramp=2.0, fade=(1.0, 0.0)):
    """A crease: a crisp step of `depth` on `path`, with a ramp `ramp` mm wide on the side `ramp_dir`
    points to that rises back to the band surface. The cut grows linearly over fade[0] mm from
    the start (a carved tip) and dies out over fade[1] mm before the end; ends past a rim run on."""
    return dict(path=path, ramp_dir=ramp_dir, depth=depth, ramp=ramp, fade=fade)


def groove(path, width=0.6, fade=(0.6, 0.6)):
    """An engraved line: a V groove `width` mm wide with 45 degree walls (0.6 x 0.3 mm is the
    finest line a 0.4 mm nozzle reproduces reliably; the real ring's lines are finer)."""
    return dict(path=path, ramp_dir=None, depth=width / 2, ramp=width / 2, fade=fade)


UP, DOWN, RIGHT = (0, 1), (0, -1), (1, 0)

# Traced from the straight-on product photo (ka_0); the far sides, which that photo does not
# show, from the 3/4 views.
KIRITO = dict(
    band=dict(width=4.8, back_width=3.0, wall=1.8, back_wall=1.6, edge_r=0.3),
    stone_d=3.6, bezel_w=0.25, bezel_h=0.25, dome_h=1.1,
    lines=[
        # left: main blade, tip 1.2 mm from the bezel; upper edge (facet above it) ...
        line([(-3.3, 0.0), (-4.2, 0.05), (-5.0, 0.03), (-5.8, 0.02), (-6.6, 0.06), (-7.2, 0.12), (-7.9, 0.19),
              (-8.6, 0.26), (-9.2, 0.32), (-9.9, 0.39), (-10.4, 0.45), (-11.0, 0.50), (-11.8, 0.53),
              (-12.7, 0.56), (-14.0, 0.62), (-15.5, 0.76), (-17.0, 0.95), (-18.0, 1.1)], UP),
        # ... and lower edge, which runs on down to the lower rim
        line([(-3.3, 0.0), (-3.9, -0.1), (-4.4, -0.2), (-5.0, -0.27), (-5.6, -0.33), (-6.3, -0.39),
              (-7.1, -0.46), (-7.8, -0.52), (-8.4, -0.57), (-9.0, -0.65), (-9.5, -0.76), (-9.9, -0.94),
              (-10.1, -1.1)], DOWN),
        # left: second blade tucked under the first; its upper edge leaves the first blade's lower edge
        line([(-8.4, -0.57), (-9.1, -0.56), (-10.2, -0.5), (-11.5, -0.4), (-12.2, -0.28), (-13.2, -0.09),
              (-14.5, 0.12), (-16.0, 0.35), (-17.5, 0.55)], DOWN, fade=(0.6, 0.0)),
        # left: facet line from below the stone to the lower rim
        line([(-3.4, -0.47), (-5.0, -0.57), (-6.5, -0.68), (-8.0, -0.8), (-9.6, -0.95), (-10.4, -1.1)],
             DOWN, 0.25, 1.5),
        # right: narrow blade pointing at the stone, rising to the hook; upper edge goes on to the rim
        line([(2.5, -0.15), (3.5, 0.12), (4.6, 0.27), (5.5, 0.37), (6.4, 0.45), (7.0, 0.5), (7.8, 0.6),
              (8.5, 0.68), (9.5, 0.76), (11.0, 0.88), (12.5, 1.0), (13.5, 1.1)], UP),
        line([(2.5, -0.15), (3.2, -0.12), (4.2, 0.0), (5.2, 0.12), (6.2, 0.24), (7.0, 0.36), (7.6, 0.42)],
             DOWN, 0.25, 1.5, (1.0, 0.6)),
        # right: the hook edge, from the blade's tail down toward the lower rim
        line([(7.0, 0.5), (7.8, 0.33), (8.4, 0.18), (9.2, 0.06), (10.0, -0.03), (10.8, -0.1), (11.6, -0.16),
              (13.0, -0.3), (14.5, -0.5), (16.0, -0.8), (17.0, -1.1)], RIGHT, fade=(0.6, 0.0)),
        # right: second diagonal parallel to the hook, from the upper rim
        line([(8.8, 1.1), (9.6, 0.75), (10.4, 0.5), (11.1, 0.3), (12.2, 0.03), (12.8, -0.15), (14.0, -0.45),
              (15.5, -0.8), (16.5, -1.1)], RIGHT, 0.25, 1.5, (0.0, 0.0)),
        # right: lower blade with its own tip; upper and lower edge
        line([(4.3, -0.28), (5.1, -0.25), (6.0, -0.24), (7.1, -0.23), (8.5, -0.24), (10.0, -0.26), (11.5, -0.3)],
             UP, 0.25, 1.5, (1.0, 1.0)),
        line([(4.3, -0.28), (5.5, -0.44), (6.8, -0.52), (8.2, -0.61), (9.5, -0.7), (10.8, -0.76), (12.0, -0.82),
              (13.5, -0.92), (15.0, -1.1)], DOWN),
        # right: long crease from beside the stone to the upper rim
        line([(2.0, 0.39), (3.0, 0.52), (4.0, 0.63), (5.5, 0.82), (6.6, 0.97), (7.2, 1.1)], UP, 0.25, 1.5),
    ],
)

ASUNA = dict(
    band=dict(width=4.8, back_width=3.0, wall=1.8, back_wall=1.6, edge_r=0.3),
    stone_d=3.6, bezel_w=0.25, bezel_h=0.25, dome_h=1.2,
    lines=[
        # left: deep recess along the upper rim, closed by the rounded front of the top feather
        line([(-12.6, 1.1), (-11.9, 0.87), (-10.7, 0.79), (-9.4, 0.73), (-8.2, 0.64), (-7.8, 0.6), (-7.6, 0.66),
              (-7.5, 0.76), (-7.55, 0.88), (-7.7, 1.1)], UP, 0.4, 1.5, (0.0, 0.0)),
        # left: stacked feathers, pointed tips away from the stone, rounded fronts toward it;
        # main feather: black upper edge, the lower edge of the flat lens above it, and its lower edge
        groove([(-12.0, 0.53), (-10.7, 0.41), (-9.4, 0.3), (-8.2, 0.18), (-7.25, 0.07), (-6.0, 0.03), (-4.9, 0.03),
                (-4.6, 0.07), (-4.5, 0.14)], fade=(1.0, 0.4)),
        groove([(-12.0, 0.53), (-10.7, 0.45), (-9.0, 0.38), (-7.5, 0.33), (-6.0, 0.29), (-4.9, 0.25), (-3.5, 0.24),
                (-2.4, 0.32)]),
        groove([(-13.0, 0.2), (-11.5, 0.05), (-10.25, -0.06), (-9.0, -0.18), (-7.5, -0.31), (-6.6, -0.39),
                (-6.0, -0.42), (-5.5, -0.36), (-5.1, -0.23), (-4.85, -0.08), (-4.75, 0.03)], fade=(0.6, 0.0)),
        # ... the feather below it
        line([(-12.0, -0.4), (-10.7, -0.6), (-9.4, -0.73), (-8.6, -0.78), (-7.5, -0.8), (-6.6, -0.8)], DOWN,
             0.25, 1.0, (1.0, 0.8)),
        # left: long sword-like line from beside the stone to the lower rim
        groove([(-1.9, -0.5), (-3.0, -0.58), (-4.5, -0.67), (-6.0, -0.77), (-7.4, -0.88), (-8.6, -0.97),
                (-9.5, -1.1)], fade=(0.6, 0.0)),
        # right: engraved line from the bezel to the upper rim
        groove([(2.17, 0.39), (3.0, 0.5), (4.17, 0.63), (5.2, 0.75), (6.17, 0.85), (7.5, 0.98), (8.3, 1.1)],
               fade=(0.0, 0.0)),
        # right: small leaf under the upper rim (engraved outline)
        groove([(7.4, 0.55), (7.9, 0.68), (8.4, 0.76), (9.0, 0.79), (9.5, 0.77), (9.7, 0.72), (9.5, 0.66),
                (9.0, 0.64), (8.4, 0.61), (7.9, 0.58), (7.4, 0.55)], fade=(0.0, 0.0)),
        # right: long feather from the fork near the stone out to the far side: lower and upper edge
        groove([(3.9, -0.06), (4.97, 0.15), (5.9, 0.24), (7.1, 0.29), (8.8, 0.24), (10.8, 0.09), (12.6, -0.12),
                (14.0, -0.35), (15.5, -0.65), (16.5, -1.1)], fade=(0.0, 0.0)),
        groove([(5.9, 0.51), (7.0, 0.53), (8.4, 0.42), (10.2, 0.18), (12.0, -0.15), (13.5, -0.45), (15.0, -0.8),
                (16.0, -1.1)], fade=(0.8, 0.0)),
        # right: the fork under the stone: a deep notch between its arms, the arm that runs on to the
        # lower rim, and the long lower feather edge
        line([(3.9, -0.06), (3.3, -0.25), (2.83, -0.45)], RIGHT, 0.35, 0.6, (0.0, 0.0)),
        groove([(2.83, -0.45), (2.5, -0.68), (2.15, -0.86), (1.9, -1.1)], fade=(0.0, 0.0)),
        line([(2.83, -0.45), (3.8, -0.39), (4.83, -0.36), (5.9, -0.35), (7.5, -0.44), (9.5, -0.64),
              (11.5, -0.79), (13.0, -0.9), (14.5, -1.1)], DOWN, 0.3, 1.0, (0.0, 0.0)),
    ],
)

STYLES = dict(kirito=KIRITO, asuna=ASUNA)


def polyline_field(px, py, path):
    """Signed distance to a polyline (+ on the left of its direction) and arc position along it."""
    best = np.full(px.shape, np.inf)
    sd = np.zeros(px.shape); along = np.zeros(px.shape)
    acc = 0.0
    for (ax, ay), (bx, by) in zip(path[:-1], path[1:]):
        dx, dy = bx - ax, by - ay
        L = np.hypot(dx, dy)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / (L * L), 0.0, 1.0)
        ex, ey = px - ax - t * dx, py - ay - t * dy
        d = np.hypot(ex, ey)
        closer = d < best
        best = np.where(closer, d, best)
        sd = np.where(closer, np.where(dx * ey - dy * ex >= 0, d, -d), sd)
        along = np.where(closer, acc + t * L, along)
        acc += L
    return sd, along, acc


def relief(s, zeta, style, half_w):
    """Depth (mm, >= 0) cut into the band by the creases."""
    zs = zeta * half_w
    cut = np.zeros_like(s)
    for ln in style["lines"]:
        p = np.array([(q[0], q[1] * half_w) for q in ln["path"]])
        for end, nxt in ((0, 1), (-1, -2)):                            # run on past the rims
            if abs(ln["path"][end][1]) >= 1.0:
                step = p[end] - p[nxt]
                p[end] = p[end] + 2.0 * step / np.hypot(*step)
        d, ramp = ln["depth"], ln["ramp"]
        lo, hi = p.min(0) - ramp - d, p.max(0) + ramp + d
        near = (s > lo[0]) & (s < hi[0]) & (zs > lo[1]) & (zs < hi[1])
        if not near.any():
            continue
        sd, along, total = polyline_field(s[near], zs[near], p)
        f0, f1 = ln["fade"]
        if ln["ramp_dir"] is None:                                     # V groove
            c = np.clip(d - np.abs(sd), 0.0, None)
        else:   # the ramp is on the side ramp_dir points to, seen from the first segment
            (ax, ay), (bx, by) = p[0], p[1]
            hx, hy = ln["ramp_dir"]
            ramp_left = (bx - ax) * hy * half_w - (by - ay) * hx >= 0
            u = sd if ramp_left else -sd                              # u > 0: ramp side
            c = np.where(u > 0, d * np.clip(1 - u / ramp, 0.0, 1.0), d * np.clip(1 + u / 0.06, 0.0, 1.0))
        fade = np.ones_like(along)
        if f0 > 0:
            fade = np.minimum(fade, np.clip(along / f0, 0.0, 1.0))
        if f1 > 0:
            fade = np.minimum(fade, np.clip((total - along) / f1, 0.0, 1.0))
        fade[(along <= 0) | (along >= total)] = 0.0                   # no cut past the ends
        cut[near] = np.maximum(cut[near], c * fade)
    return cut


def stone(s, z, style):
    """Bezel + cabochon height above the band, and a mask that keeps the creases off the setting."""
    d = np.hypot(s, z)
    rs = style["stone_d"] / 2
    rb = rs + style["bezel_w"]
    bh, dh = style["bezel_h"], style["dome_h"]
    h = np.clip(bh - (d - rb), 0.0, bh)                      # bezel with a 45 degree outer wall
    rd = (rs ** 2 + dh ** 2) / (2 * dh)
    dome = np.sqrt(np.clip(rd ** 2 - d ** 2, 0, None)) - (rd - dh)
    h = np.where(d < rs, bh + dome, h)
    return h, (d > rb).astype(float)


def band_shape(theta, band):
    """Lower rim z, upper rim z and wall at angle theta (0 = stone). The lower rim stays flat (it is
    the bed side); the band narrows from the top toward the open back."""
    k = np.clip((np.abs(theta) - np.radians(75)) / np.radians(105), 0.0, 1.0)
    k = k * k * (3 - 2 * k)
    t = band["wall"] + (band["back_wall"] - band["wall"]) * k
    w = band["width"] + (band["back_width"] - band["width"]) * k
    lo = np.full_like(theta, -band["width"] / 2)
    return lo, lo + w, t


def overlap_angles(theta):
    """Angles measured so the open back's overlap runs continuously from BACK_UPPER to BACK_LOWER."""
    return np.where(theta < 0, theta + 2 * np.pi, theta)


def back_seam(theta, z, lo, hi, ro):
    """Closed band only: V grooves (0.6 wide, 0.3 deep) where the real ring's two overlapping ends
    meet: a seam along the middle of the back, and the two end faces of the strips."""
    a = overlap_angles(theta)
    mid = (lo + hi) / 2
    d_seam = np.where((a > BACK_UPPER) & (a < BACK_LOWER), np.abs(z - mid), np.inf)
    arc = lambda ang: np.abs(a - ang) * ro
    d_up = np.where(z > mid, arc(BACK_UPPER), np.inf)
    d_low = np.where(z < mid, arc(BACK_LOWER), np.inf)
    d = np.minimum(d_seam, np.minimum(d_up, d_low))
    return np.clip(0.3 - d, 0.0, None)


def edge_drop(z, lo, hi, edge_r):
    """Radial drop that rounds the outer edges."""
    e = np.minimum(z - lo, hi - z)
    return np.where(e < edge_r, edge_r - np.sqrt(np.clip(edge_r ** 2 - (edge_r - e) ** 2, 0, None)), 0.0)


def limit_overhang(r, z):
    """Going up each column, never let the radius grow faster than z rises (45 degrees)."""
    r = r.copy()
    for i in range(1, r.shape[0]):
        r[i] = np.minimum(r[i], r[i - 1] + (z[i] - z[i - 1]))
    return r


def smooth(a, passes=3):
    """Small binomial blur over the grid: rounds the crisp creases by ~0.06 mm so they mesh cleanly."""
    for _ in range(passes):
        a = 0.25 * (np.roll(a, 1, 1) + 2 * a + np.roll(a, -1, 1))
        a[1:-1] = 0.25 * (a[:-2] + 2 * a[1:-1] + a[2:])
    return a


def outer_surface(ri, style, theta, n_z, seam=True):
    band = style["band"]
    lo, hi, t = band_shape(theta, band)                       # (n_theta,)
    u = np.linspace(-1.0, 1.0, n_z)[:, None]
    v = 0.5 * (u + np.sin(u * np.pi / 2))                     # denser rows near the rims
    z = (lo + hi) / 2 + v * (hi - lo) / 2                     # (n_z, n_theta)
    ro = ri + band["wall"]
    s = np.broadcast_to(theta * ro, z.shape)
    half_front = band["width"] / 2
    st, keep_off = stone(s, z, style)
    cut = relief(s, z / half_front, style, half_front) * keep_off
    if seam:
        cut = np.maximum(cut, back_seam(theta, z, lo, hi, ro))
    r = ri + t - edge_drop(z, lo, hi, band["edge_r"]) - smooth(cut) + st
    return z, limit_overhang(r, z)


def build_band(inner_d, style_name, seam=True, grid=GRID):
    """Closed band as one watertight height-field mesh."""
    style = STYLES[style_name]
    band = style["band"]
    ri = (inner_d + FIT) / 2
    n_theta = int(np.ceil(2 * np.pi * (ri + band["wall"]) / grid / 8) * 8)
    theta = np.linspace(-np.pi, np.pi, n_theta, endpoint=False)
    n_z = int(band["width"] / grid * 0.8) | 1
    z, r = outer_surface(ri, style, theta, n_z, seam)

    outer = np.stack([r * np.cos(theta), r * np.sin(theta), z], -1)          # (n_z, n_theta, 3)
    c = INNER_CHAMFER
    zb, zt = z[0], z[-1]
    inner_rows = [(ri + c, zb), (ri, zb + c), (ri, zt - c), (ri + c, zt)]
    inner = np.stack([np.stack([rr * np.cos(theta), rr * np.sin(theta), zz], -1) for rr, zz in inner_rows])

    n_o, n_i = outer.shape[0], inner.shape[0]
    verts = np.concatenate([outer.reshape(-1, 3), inner.reshape(-1, 3)])
    j = np.arange(n_theta)
    j1 = (j + 1) % n_theta
    oi = lambda i, jj: i * n_theta + jj
    ii = lambda i, jj: n_o * n_theta + i * n_theta + jj
    faces = []
    for i in range(n_o - 1):      # outer wall, normals out
        faces += [np.stack([oi(i, j), oi(i, j1), oi(i + 1, j1)], 1), np.stack([oi(i, j), oi(i + 1, j1), oi(i + 1, j)], 1)]
    for i in range(n_i - 1):      # inner wall, normals in
        faces += [np.stack([ii(i, j), ii(i + 1, j1), ii(i, j1)], 1), np.stack([ii(i, j), ii(i + 1, j), ii(i + 1, j1)], 1)]
    # bottom (normal -z) and top (+z) rim faces
    faces += [np.stack([oi(0, j), ii(0, j1), oi(0, j1)], 1), np.stack([oi(0, j), ii(0, j), ii(0, j1)], 1)]
    faces += [np.stack([oi(n_o - 1, j), oi(n_o - 1, j1), ii(n_i - 1, j1)], 1),
              np.stack([oi(n_o - 1, j), ii(n_i - 1, j1), ii(n_i - 1, j)], 1)]
    return trimesh.Trimesh(verts, np.concatenate(faces), process=False)


def sweep(theta, section):
    """Watertight solid swept around Z: section(th) -> (n, 2) closed (r, z) loop, counter-clockwise."""
    loops = [section(th) for th in theta]
    n = len(loops[0])
    verts = np.concatenate([np.stack([l[:, 0] * np.cos(th), l[:, 0] * np.sin(th), l[:, 1]], -1)
                            for th, l in zip(theta, loops)])
    faces = []
    k = np.arange(n)
    k1 = (k + 1) % n
    for a in range(len(theta) - 1):
        b0, b1 = a * n, (a + 1) * n
        faces += [np.stack([b0 + k, b0 + k1, b1 + k1], 1), np.stack([b0 + k, b1 + k1, b1 + k], 1)]
    for base, flip in ((0, False), ((len(theta) - 1) * n, True)):     # end caps (fan)
        cen = len(verts)
        verts = np.vstack([verts, verts[base:base + n].mean(0)])
        cap = np.stack([np.full(n, cen), base + k1, base + k], 1)
        faces.append(cap[:, ::-1] if flip else cap)
    m = trimesh.Trimesh(verts, np.concatenate(faces), process=False)
    if m.volume < 0:
        m.invert()
    return m


def open_back_cutter(ri, style):
    """Material removed to make the real open, overlapping back: a flat slot between the two
    strips and a clearance at each strip end. A thin web on the inside keeps the upper strip
    attached at BACK_UPPER, so the slot's ceiling prints as a bridge between two anchors; snip
    the web after printing to open the ring."""
    band = style["band"]
    r0, r1 = ri - 0.5, ri + band["wall"] + 1.5
    lo = -band["width"] / 2
    z_mid = lo + band["back_width"] / 2
    z0, z1 = z_mid - SPLIT_GAP / 2, z_mid + SPLIT_GAP / 2
    big = band["width"]

    def box(ra, rb, za, zb):
        return lambda th: np.array([(ra, za), (rb, za), (rb, zb), (ra, zb)])

    ro = ri + band["back_wall"]
    end = END_GAP / ro
    parts = [sweep(np.linspace(BACK_UPPER, BACK_LOWER, 120), box(r0, r1, z0, z1)),
             sweep(np.linspace(BACK_UPPER - end, BACK_UPPER + 0.01, 12), box(ri + WEB, r1, z0 + 0.05, big)),
             sweep(np.linspace(BACK_LOWER - 0.01, BACK_LOWER + end, 12), box(r0, r1, -big, z1 - 0.05))]
    return trimesh.boolean.union(parts, engine="manifold")


def build_ring(inner_d, style_name, open_back=False, grid=GRID):
    """The printable ring, sitting on the bed. open_back cuts the real overlapping opening."""
    mesh = build_band(inner_d, style_name, seam=not open_back, grid=grid)
    if open_back:
        cutter = open_back_cutter((inner_d + FIT) / 2, STYLES[style_name])
        mesh = trimesh.boolean.difference([mesh, cutter], engine="manifold")
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
    return mesh


def build_gauge(inner_ds, height_step=0.5):
    """Thin test rings, taller = bigger, laid out left to right."""
    parts, x = [], 0.0
    for k, d in enumerate(inner_ds):
        h = 1.5 + height_step * k
        ring = trimesh.creation.annulus(r_min=(d + FIT) / 2, r_max=(d + FIT) / 2 + 1.2, height=h)
        ring.apply_translation([x + (d / 2 + 1.2), 0, h / 2])
        x += d + 4.5
        parts.append(ring)
    return trimesh.util.concatenate(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kirito-id", type=float, default=18.9, help="Kirito inner diameter mm (US 9)")
    ap.add_argument("--asuna-id", type=float, default=14.9, help="Asuna inner diameter mm (US 4)")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).parent / "stl"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    variants = ["closed"]
    if importlib.util.find_spec("manifold3d"):
        variants.append("open")
    else:
        print("manifold3d not installed: skipping the *_open variants (pip install manifold3d)")
    for name, d in (("kirito", a.kirito_id), ("asuna", a.asuna_id)):
        for variant in variants:
            m = build_ring(d, name, open_back=variant == "open")
            assert m.is_watertight and m.is_winding_consistent and m.volume > 0, f"{name} {variant}: bad solid"
            path = out / f"{name}_ring_id{d:.1f}mm_{variant}.stl"
            m.export(path)
            print(f"{path.name}: {len(m.faces)} tris, volume {m.volume:.0f} mm3, "
                  f"size over the stone {m.bounds[1][0] - m.bounds[0][0]:.1f} mm, height {m.bounds[1][2]:.2f} mm")

    sizes = [14.0, 14.9, 15.7, 16.5, 17.3, 18.1, 18.9, 19.8]
    g = build_gauge(sizes)
    g.export(out / "size_gauge.stl")
    print("size_gauge.stl: inner diameters (mm) shortest->tallest:", sizes)


if __name__ == "__main__":
    main()
