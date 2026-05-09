# Pocket Deck dither + fields package

Pure-MicroPython dithering and animated-field modules for the Pocket Deck's
400×240 monochrome LCD. Adds Floyd-Steinberg dithering (complementing the
existing Bayer ordered dither in `set_dither()`) and a small library of
demoscene-style field generators.

No C changes required. Everything sits on top of the existing `vscreen`
API, using `draw_xbm()` as the final blit primitive.

## Installation

Copy the files to the Pocket Deck's SD card:

```
/sd/lib/dither.py
/sd/lib/fields.py
/sd/py/plasma_demo.py
/sd/py/dither_compare.py
```

The `lib` directory is on the default import path. The `py` directory is
where user applications live.

## Running

From the command line on screen 2:

```
r plasma_demo                 # 80x80, FS — device default
r plasma_demo 40              # 40x40, FS — fast shim iteration
r plasma_demo 120 bayer       # 120x120 starting in Bayer mode
r dither_compare              # 80x80 panels, FS vs Bayer side by side
r dither_compare 40           # 40x40 panels — fast shim iteration
r dither_compare 120          # 120x120 panels — largest practical comparison
r fields_demo                 # 80x80, cycle through plasma/metaballs/tunnel
r fields_demo 40              # 40x40 — fast shim iteration
r fields_demo 120 bayer       # 120x120 starting in Bayer mode
```

In `plasma_demo` and `fields_demo`, press space to toggle between FS and
Bayer live. In `fields_demo`, use left/right arrow keys to cycle between
field types. Touch the bottom-right touchpad button to exit any demo.

Recommended sizes:
- **40×40** — comfortable on the shim for layout and behavior iteration
- **80×80** — device default, animates well on the deck
- **120×120** — bigger panel, ~10–15 fps on device for FS, faster for Bayer
- **160×160** — `plasma_demo` only; `dither_compare` doesn't fit two panels at this size

## Module overview

### `dither.py`
Converts 8-bit grayscale bytearrays to 1-bit MSB-first XBM buffers.

- `bayer_dither_to_xbm(gray, w, h)` — 4×4 ordered dither
- `fs_dither_to_xbm(gray, w, h, err_a=None, err_b=None)` — Floyd-Steinberg
- `dither_to_xbm(gray, w, h, mode="fs")` — dispatch wrapper
- `draw_gray_rect(v, x, y, w, h, gray, mode="fs")` — dither and blit
- `draw_field(v, x, y, w, h, field_fn, t, mode="fs", gray_buf=None)` — generate and blit
- `draw_gradient_box(v, x, y, w, h, g0, g1, direction="v", mode="fs")` — convenience

Pass a pre-allocated `err_a`/`err_b` to `fs_dither_to_xbm` across frames
to avoid per-call allocation. Each error buffer is `2 * (w + 2)` bytes.

### `fields.py`
Time-varying grayscale field generators.

- `Plasma(w, h, speeds=(2,3,1,5))` — classic 4-term interference plasma
- `Metaballs(w, h, n=3, strength=96)` — inverse-square blobs
- `Tunnel(w, h, speed=3)` — angular+radial phase field

Each class exposes `.step()` returning its internal grayscale bytearray.
The buffer is reused across calls, so don't retain references across
frames.

## Field-size guidance

| Size       | Pixels | Memory  | FS fps | Bayer fps | Use case          |
|------------|--------|---------|--------|-----------|-------------------|
| 80×80      | 6.4k   | ~14 KB  | 30+    | 60+       | animated panel    |
| 160×120    | 19k    | ~42 KB  | 10–15  | 30+       | bigger panel      |
| 400×240    | 96k    | ~206 KB | 2–4    | 10–15     | static or slow    |

Numbers are rough estimates; benchmark on your device. FS is inherently
serial (error diffusion has a data dependency between adjacent pixels)
so it doesn't parallelize the way Bayer does.

## Design notes

- `dither.py` is a consumer of grayscale data; `fields.py` is a producer.
  They don't know about each other beyond the grayscale bytearray
  interface. Write your own field, feed it to the dither layer.
- Both dither modes produce MSB-first XBM, matching `vscreen.draw_xbm()`
  and `pngreader.py` conventions.
- The existing `v.set_dither(level)` is untouched and still works for
  per-primitive ordered dithering of shapes and text. The two systems
  are complementary.
- Viper kernels fall back to plain-Python implementations automatically
  if viper is unavailable (useful for host-side testing).

## Extending

To add a new field type, create a class with a `.step()` method that
returns a grayscale bytearray. Model it after `Plasma`:

1. Precompute any expensive tables in `__init__`.
2. Allocate `self.gray = bytearray(w * h)` once.
3. Write a `@micropython.viper` kernel that fills it in place.
4. Call the kernel from `step()` after advancing any time/state.

To add a new dither algorithm, write a function matching the signature
of `bayer_dither_to_xbm`, then add a branch to `dither_to_xbm`. Good
candidates: Jarvis-Judice-Ninke (larger error kernel than FS), Atkinson
(Apple II style, washes out highlights), or blue noise (stateless but
better than Bayer).

# Acknowledgements

* AI-assisted development using Anthropic Claude Opus 4.7.