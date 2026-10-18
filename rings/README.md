# Kirito & Asuna couple rings (Ender 3)

Inspired by Inner Anime's "Kirito & Asuna Rings": black Kirito band and silver
Asuna band, each with a round stone in a bezel and swept blade grooves.
The grooves are an approximation traced from the shop's marketing photos (no
dimensions were published), so treat this as v1.

| File | Who | Inner diameter | Assumed size |
|---|---|---|---|
| `stl/kirito_ring_id18.9mm.stl` | Kirito (you) | 18.9 mm (+0.2 mm print fit) | size 9 read as US 9 |
| `stl/asuna_ring_id14.9mm.stl` | Asuna (gf) | 14.9 mm (+0.2 mm print fit) | size 4 read as US 4 |
| `stl/size_gauge.stl` | both | 8 thin test rings | see below |

**Check the size first.** "EU 9 / 4" does not map to EU (circumference) sizing,
so US was assumed. Print `size_gauge.stl` (about 15 min), try the rings on the
right finger and pick the one that slides over the knuckle snugly. Rings are
left to right, taller = bigger: 14.0, 14.9, 15.7, 16.5, 17.3, 18.1, 18.9,
19.8 mm inner diameter. Then regenerate:

    python3 make_rings.py --kirito-id 18.9 --asuna-id 14.9

Needs `numpy` and `trimesh` (`pip install numpy trimesh`).

## Dimensions
- Band 5.0 mm wide, 1.8 mm thick, rounded outer edges, 0.3 mm comfort chamfer inside.
- Stone: 3.6 mm round dome, bezel 0.4 mm raised, dome 1.0 mm above the band.
- Grooves 0.4 mm deep, 0.7 mm wide. Kirito = angular, Asuna = flowing curves.
- Closed bands (no adjustable gap): a thin open PLA back would snap.

## Printing (stock Ender 3, 0.4 mm nozzle)
Print flat as exported (ring axis vertical), no supports, no brim. Steepest
overhang is the stone dome at about 37 degrees. Put the Z seam on the back.

**PLA**: 0.12 mm layers (0.16 ok), 4 walls, 100 % infill, 205 to 210 C, bed 60 C,
fan 100 % after layer 1, outer wall 30 mm/s. Rigid, so it must slide over the
knuckle, and it softens in heat and hand sweat over time. A coat of clear
epoxy or UV resin makes it last.

**TPU**: 0.2 mm layers, 3 walls, 100 % infill, 220 to 230 C, bed 50 to 60 C, 15 to
20 mm/s, retraction minimal. Stretches over the knuckle and is far more
comfortable for everyday wear, but grooves come out softer. A stock bowden
Ender 3 prints TPU slowly and can jam, so try PLA first.

**Colours**: Kirito black, Asuna silver or silk-silver. Paint or dab the dome
with deep-blue glitter nail polish (Kirito) and pearly pale blue (Asuna), as in
the reference photos.
