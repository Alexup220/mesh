# Kirito & Asuna couple rings (Ender 3)

Printable copies of Inner Anime's "Kirito & Asuna Rings" (Sword Art Online):
the dark gunmetal Kirito band with a round deep-blue stone, and the polished
silver Asuna band with a pale-blue moonstone cabochon. Each ring is generated
by `make_rings.py`; the sculpted creases were traced from the shop photos
(see "How the shape was taken from the photos" below).

## Files

| File | What it is |
|---|---|
| `stl/kirito_ring_id18.9mm_closed.stl` | **Kirito, recommended.** Closed band, front identical to the real ring, the open back shown as engraved seam lines. |
| `stl/asuna_ring_id14.9mm_closed.stl` | **Asuna, recommended.** Same, for Asuna. |
| `stl/kirito_ring_id18.9mm_open.stl` | Kirito with the real open, overlapping back (two strips). Optional, see "Open or closed". |
| `stl/asuna_ring_id14.9mm_open.stl` | Asuna with the real open, overlapping back. Optional. |
| `stl/size_gauge.stl` | 8 thin test rings to check the size first. |
| `preview/kirito_compare.png`, `preview/asuna_compare.png` | Reference photo crop (left) beside this model rendered from the same fitted camera (right): front, close-up, 3/4 view. |
| `preview/*_compare_unrolled.png` | The band surface of photo and model unrolled onto the same mm grid, to compare where every crease runs. |
| `preview/*_views_closed.png`, `preview/*_views_open.png` | The STLs from the front, 3/4, side, top, back and inside. |

Sizes: Kirito (you) 18.9 mm inner diameter (US 9), Asuna 14.9 mm (US 4);
the STLs are 0.2 mm bigger (19.1 / 15.1 mm, measured on the mesh) to make up
for FDM shrink and elephant foot.

**Check the size first.** "EU 9 / 4" does not map to EU (circumference) sizing,
so US was assumed. Print `size_gauge.stl` (about 15 min), try the rings on the
right finger and pick the one that slides over the knuckle snugly. Rings are
left to right, taller = bigger: 14.0, 14.9, 15.7, 16.5, 17.3, 18.1, 18.9,
19.8 mm nominal inner diameter. Then regenerate:

    python3 make_rings.py --kirito-id 18.9 --asuna-id 14.9

Needs `numpy` and `trimesh`; the `*_open` files also need `manifold3d`
(`pip install numpy trimesh manifold3d`). The pattern keeps its size in mm at
any ring size, like the real one-size ring.

## Dimensions (measured on the exported meshes)

| | Kirito | Asuna |
|---|---|---|
| Inner diameter (mesh) | 19.10 mm | 15.10 mm |
| Band outer diameter | 22.7 mm | 18.7 mm |
| Over the stone | 23.85 mm | 19.95 mm |
| Band width: front / back | 4.8 / 3.0 mm | 4.8 / 3.0 mm |
| Wall: front / back | 1.8 / 1.6 mm (min. 1.48 mm under the deepest crease) | 1.8 / 1.6 mm (min. 1.47 mm) |
| Stone | 3.6 mm round cabochon, 1.1 mm high, in a 0.25 mm bezel | 3.6 mm, 1.2 mm high, 0.25 mm bezel |
| Creases | 0.25 to 0.3 mm steps (0.22 to 0.28 mm after rounding) with 1.5 to 2 mm ramps | V lines 0.6 mm wide, 0.22 to 0.25 mm deep after rounding; 0.25 to 0.4 mm steps |
| Mesh | 232k triangles, 11.6 MB, watertight, 1 body | 191k triangles, 9.5 MB |

All four ring STLs are watertight, consistently wound, one body, no
degenerate faces. The closed bands have no face steeper than 45 degrees
facing down; the open ones have only the bridged slot described below.

## Open or closed

The real ring is open at the back: the band splits into an upper and a lower
strip that overlap for about 57 degrees (from 133 to 190 degrees round from
the stone), so it can be bent to size. In 1.6 mm PLA that bending would snap
the strips, and a 3 mm-wide back in two strips leaves only 1.3 mm per strip.

* **`*_closed` (recommended, PLA or TPU).** Exactly the same front, stone and
  creases. The back is a solid band with 0.3 mm V grooves where the strips of
  the real ring meet, so the overlap still reads at a glance. Strong, prints
  without supports.
* **`*_open` (optional, best in TPU).** The real overlap: 0.4 mm slot between
  the strips and a 1 mm gap at each strip end. Strips are 1.3 mm tall and
  1.6 mm thick. To print without supports, a 0.4 mm web on the inside keeps
  the upper strip attached at its end, so the slot's ceiling is a 9 mm
  (Asuna) to 11 mm (Kirito) bridge anchored at both ends. After printing, cut the web (the thin wall
  inside the gap in the top rim) with flush cutters to open the ring. Expect
  some sag on that bridge; if the strips stick together, run a hobby knife
  through the slot. In PLA it is a look-alike, not really adjustable; in TPU
  it flexes like the real one.

## Printing (stock Ender 3, 0.4 mm nozzle)

Print flat as exported (ring axis vertical, flat lower rim on the bed), no
supports, no brim. Put the Z seam on the back. Every downward-facing slope of
the closed bands is at most 45 degrees: the lower half of the stone dome and
the downward crease walls were limited to 45 degrees for that.

**PLA**: 0.12 mm layers (0.16 ok), 4 walls, 100 % infill, 205 to 210 C, bed 60 C,
fan 100 % after layer 1, outer wall 30 mm/s. Rigid, so it must slide over the
knuckle, and it softens in heat and hand sweat over time. A coat of clear
epoxy or UV resin makes it last. For `*_open`, turn bridge detection on and
keep the fan at 100 % on the bridge.

**TPU**: 0.2 mm layers, 3 walls, 100 % infill, 220 to 230 C, bed 50 to 60 C, 15 to
20 mm/s, retraction minimal. Stretches over the knuckle and is far more
comfortable for everyday wear, but creases come out softer. A stock bowden
Ender 3 prints TPU slowly and can jam, so try PLA first.

**Colours**: Kirito black or dark grey (gunmetal), Asuna silver or silk-silver.
Paint the dome with deep-blue glitter nail polish (Kirito) and pearly pale
blue (Asuna), as in the photos. A dark wash wiped off the surface fills the
creases and brings the lines out like on the real rings.

## How the shape was taken from the photos

The shop has five pictures (`ka_0` both rings, `ka_1` on a hand, `ka_2` Kirito
3/4, `ka_3` Asuna 3/4, `ka_4` both rings). For each picture a camera pose and a
plain tapered band were fitted to the ring's silhouette and to landmarks
(rim edges, stone centre); every photo was then unrolled onto the band surface
in mm from the stone, and the creases were traced on those unrolled images.
The model is checked by rendering it from the same fitted cameras
(`preview/*_compare*.png`).

* `ka_4` is `ka_0` mirrored; `ka_0`, `ka_2` and `ka_3` agree on which way the
  pattern runs, so `ka_0` is the true orientation.
* Kirito's and Asuna's rings are different designs, not mirror images. Kirito:
  long pointed blades, the main one stops 1.2 mm from the bezel on the left;
  on the right a narrow blade rises to a hook that sweeps down to the lower
  rim. Asuna: a deep recess under the upper rim on the left with stacked,
  round-fronted feathers below it and a long diagonal line to the lower rim;
  on the right a line from the bezel to the upper rim, a small leaf, and a
  forked notch under the stone with long feathers running to the back.
* Scale: the band is 0.45 to 0.51 times the outer radius wide in every fit,
  and the stone 0.35 times. On the hand photo the Kirito band is about 4.7 mm
  if the finger is about 20 mm wide, which gives a 4.8 mm band and a 3.6 mm
  stone, with the photographed Kirito ring about 20.8 mm across and Asuna's
  0.92 times that (from the shot with both rings).

## Differences from the real product / things approximated

* **The photos are not real photos.** The shop's own file names show that
  three of the five (`ka_2`, `ka_3`, `ka_4`) are AI-generated images and the
  other two are AI-upscaled. The 3/4 views do not agree with the front view in every
  detail (Asuna's especially), so an exact copy of "the" ring is not
  defined. The front of each ring (about 10 mm either side of the stone) is
  traced from `ka_0`, the clearest shot; the far sides only from the
  oblique 3/4 views and are less certain.
* Scale is from the hand photo and the rings' own proportions, about +-10 %.
* Lines enlarged: the real hairlines are about 0.2 mm; here they are 0.6 mm
  wide and at least 0.22 mm deep so a 0.4 mm nozzle reproduces them. Crisp
  creases are rounded by about 0.06 mm.
* Wall 1.8 mm (1.6 mm at the back) instead of about 1.0 to 1.3 mm (metal
  ring), so the ring is up to 1.6 mm bigger across outside. Back 3.0 mm wide
  instead of about 2.5 mm, for strength.
* The lower half of the stone dome is limited to 45 degrees for printing, so
  it is a little more conical than the real cabochon there.
* The stone is part of the print (paint it); a separate glass stone is not
  modelled.
* Materials (titanium/silver, black plating, glittery blue stone, moonstone)
  can only be imitated with filament colour and paint.
* `*_closed`: the open back is shown as grooves only. `*_open`: needs the web
  cut after printing, and the slot's bridge may sag a little.
