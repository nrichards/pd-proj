# Pocket Deck City Demo

A demoscene-style infinite procedural city for the Pocket Deck, in the
tradition of Farbrausch / Conspiracy / ASD wireframe vector productions.
The camera flies through a procedurally-generated cityscape on a spline
path, alternating between low-altitude weaving through buildings and
high-altitude horizon sweeps. Built on the deck's `dsplib` 3D pipeline
and developed against the desktop pygame simulator.

## Status

Milestone 1 of 8 complete: Catmull-Rom camera spline + look-at view
matrix verified against a reference cube. See "Roadmap" below.

## Running

On the desktop simulator:

```bash
python -m pdeck_sim.runner lib/city_app.py
python -m pdeck_sim.runner lib/examples/cube_stress.py
```

On the deck, sync `lib/` over and launch `city` (or `city_app` if the
launcher menu doesn't pick up packages directly).

Shim controls (pygame window):

- `Q` — exit the running demo
- `F5` — reload the app from disk
- `F11` — toggle 2x scale
- `ESC` — quit

## Layout

```
lib/city/                     City demo package
    __init__.py               Entry point + main render loop
    camera.py                 Catmull-Rom spline + view matrix

lib/city_app.py               Stub launcher for the shim runner
                              (also a clean menu entry on device)

lib/examples/cube_stress.py   FPS calibration utility
```

## Roadmap

1. **Camera + spline + view matrix** — done
2. Chunk system + single building type
3. Building variety + filled rendering with depth fog
4. PCB-trace ground (Manhattan + 45° routing, pads, vias)
5. Hybrid wireframe edges on near buildings
6. Procedural windows with twinkle (rare, dense on "hero" buildings)
7. Starfield above horizon
8. Polish: speed curves, render mode toggle, HUD

## Disc world (deferred)

Future direction: instead of an infinite plane, plant the city on a
finite disc floating in space (cf. Discworld / Dark City). Replaces
the horizon line with an edge-of-world transition to starfield;
chunks outside the disc boundary stop spawning. Mostly a chunk-mask
change once the chunk system is in.

## Notes on the shim

The shim's vsync cap is 60 fps. Stress numbers from the Mac are
useful negative results — they tell us when CPython is *not* the
bottleneck — but they don't predict on-device performance. The deck's
`dsplib` is C and much faster than the shim's Python fallback; the
real budget comes from running `cube_stress` on the deck itself.