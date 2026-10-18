"""Generate printable Kirito & Asuna (Inner Anime style) couple rings as STL.

Each ring is a watertight height-field: a closed band whose outer surface is
displaced by a stone bezel/dome and swept blade grooves. Print axis is Z (ring
lies flat on the bed), so no supports are needed (steepest overhang ~37 deg).

Usage:
    python3 make_rings.py                       # default sizes
    python3 make_rings.py --kirito-id 18.9 --asuna-id 14.9
"""
import argparse
import pathlib

import numpy as np
import trimesh

WIDTH = 5.0          # band height along the finger (mm)
WALL = 1.8           # band thickness (mm) - 4+ perimeters at 0.4 nozzle
FIT = 0.2            # added to the inner diameter to offset FDM shrink/elephant foot
EDGE_R = 0.5         # outer edge roundover (mm)
INNER_CHAMFER = 0.3  # comfort chamfer / elephant-foot relief on inner edges

STONE_R = 1.8        # cabochon radius
BEZEL_W = 0.5        # bezel ring width around the stone
BEZEL_H = 0.4        # bezel height above the band
DOME_H = 0.6         # dome height above the bezel plateau
GROOVE_D = 0.4       # groove depth
GROOVE_HW = 0.35     # groove half-width (V profile)

N_THETA = 900
N_Z = 101


def bezier(p0, p1, p2, p3, n=24):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def groove_paths(style):
    """Groove centre-lines in (arc mm, z mm from band centre) for s > 0.

    The pattern is point-symmetric (s,z) -> (-s,-z) so the grooves 'sweep'
    around the stone like in the reference photos.
    """
    if style == "kirito":  # angular, blade-like
        right = [
            np.array([(2.8, 0.45), (5.2, 1.75), (9.0, 1.75)]),
            np.array([(2.8, -0.45), (5.2, -1.75), (9.0, -1.75)]),
            np.array([(3.1, 0.0), (11.5, 0.0)]),
            np.array([(10.0, 1.75), (11.8, 0.0), (10.0, -1.75)]),
        ]
    else:  # asuna: same layout, flowing curves
        right = [
            bezier((2.8, 0.45), (5.0, 0.9), (6.5, 1.75), (9.2, 1.75)),
            bezier((2.8, -0.45), (5.0, -0.9), (6.5, -1.75), (9.2, -1.75)),
            bezier((3.1, 0.0), (6.0, 0.5), (8.5, -0.5), (11.5, 0.0)),
            bezier((10.0, 1.75), (11.6, 0.9), (11.6, -0.9), (10.0, -1.75)),
        ]
    paths = []
    for p in right:
        paths.append(p)
        paths.append(-p)
    return paths


def dist_to_paths(s, z, paths):
    best = np.full(s.shape, np.inf)
    pts = np.stack([s, z], axis=-1)
    for path in paths:
        for a, b in zip(path[:-1], path[1:]):
            ab = b - a
            t = np.clip(((pts - a) @ ab) / (ab @ ab), 0.0, 1.0)
            proj = a + t[..., None] * ab
            best = np.minimum(best, np.linalg.norm(pts - proj, axis=-1))
    return best


def outer_surface(ro, style, n_theta, n_z):
    theta = np.linspace(-np.pi, np.pi, n_theta, endpoint=False)
    z = np.linspace(0.0, WIDTH, n_z)
    th, zz = np.meshgrid(theta, z)          # (n_z, n_theta)
    s = th * ro                             # arc length from stone centre
    zc = zz - WIDTH / 2

    # edge roundover
    e = np.minimum(zz, WIDTH - zz)
    drop = np.where(e < EDGE_R, EDGE_R - np.sqrt(np.clip(EDGE_R ** 2 - (EDGE_R - e) ** 2, 0, None)), 0.0)

    # stone: bezel ring + dome
    d = np.hypot(s, zc)
    h = np.zeros_like(d)
    outer_edge = STONE_R + BEZEL_W
    ramp = np.clip((outer_edge - d) / 0.15, 0.0, 1.0)
    h = np.maximum(h, BEZEL_H * ramp)
    rd = (STONE_R ** 2 + DOME_H ** 2) / (2 * DOME_H)
    dome = np.sqrt(np.clip(rd ** 2 - d ** 2, 0, None)) - (rd - DOME_H)
    h = np.where(d < STONE_R, BEZEL_H + dome, h)

    # blade grooves (kept away from the stone and the band edges)
    gd = dist_to_paths(s, zc, groove_paths(style))
    groove = GROOVE_D * np.clip(1 - gd / GROOVE_HW, 0.0, 1.0)
    groove *= (d > outer_edge + 0.15)
    r = ro - drop + h - groove
    return theta, z, r


def build_ring(inner_d, style, n_theta=N_THETA, n_z=N_Z):
    ri = (inner_d + FIT) / 2
    ro = ri + WALL
    theta, z, r = outer_surface(ro, style, n_theta, n_z)

    def ring_xyz(rr, zz):
        return np.stack([rr * np.cos(theta), rr * np.sin(theta), np.full_like(theta, zz)], -1)

    outer = np.stack([r * np.cos(theta), r * np.sin(theta), np.broadcast_to(z[:, None], r.shape)], -1)
    inner_rows = [(ri + INNER_CHAMFER, 0.0), (ri, INNER_CHAMFER),
                  (ri, WIDTH - INNER_CHAMFER), (ri + INNER_CHAMFER, WIDTH)]
    inner = np.stack([ring_xyz(rr, zz) for rr, zz in inner_rows])  # (4, n_theta, 3)

    n_o, n_i = outer.shape[0], inner.shape[0]
    verts = np.concatenate([outer.reshape(-1, 3), inner.reshape(-1, 3)])
    oi = lambda i, j: i * n_theta + (j % n_theta)
    ii = lambda i, j: n_o * n_theta + i * n_theta + (j % n_theta)

    faces = []
    for j in range(n_theta):
        for i in range(n_o - 1):      # outer wall, normals out
            faces += [(oi(i, j), oi(i, j + 1), oi(i + 1, j + 1)), (oi(i, j), oi(i + 1, j + 1), oi(i + 1, j))]
        for i in range(n_i - 1):      # inner wall, normals in
            faces += [(ii(i, j), ii(i + 1, j + 1), ii(i, j + 1)), (ii(i, j), ii(i + 1, j), ii(i + 1, j + 1))]
        # bottom (normal -z) and top (+z) annuli
        faces += [(oi(0, j), ii(0, j + 1), oi(0, j + 1)), (oi(0, j), ii(0, j), ii(0, j + 1))]
        faces += [(oi(n_o - 1, j), oi(n_o - 1, j + 1), ii(n_i - 1, j + 1)),
                  (oi(n_o - 1, j), ii(n_i - 1, j + 1), ii(n_i - 1, j))]
    mesh = trimesh.Trimesh(verts, np.array(faces), process=False)
    mesh.merge_vertices()
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

    for name, d in (("kirito", a.kirito_id), ("asuna", a.asuna_id)):
        m = build_ring(d, name)
        assert m.is_watertight and m.volume > 0, f"{name} mesh is not a valid solid"
        path = out / f"{name}_ring_id{d:.1f}mm.stl"
        m.export(path)
        print(f"{path.name}: {len(m.faces)} tris, volume {m.volume:.0f} mm3, "
              f"outer dia {m.bounds[1][0] - m.bounds[0][0]:.1f} mm")

    sizes = [14.0, 14.9, 15.7, 16.5, 17.3, 18.1, 18.9, 19.8]
    g = build_gauge(sizes)
    g.export(out / "size_gauge.stl")
    print("size_gauge.stl: inner diameters (mm) shortest->tallest:", sizes)


if __name__ == "__main__":
    main()
