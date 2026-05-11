# Changelog

All notable changes to the pocketdeck_dither package are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
MAJOR for breaking API changes, MINOR for backward-compatible new features,
PATCH for backward-compatible bug fixes.

The single source of truth for the current version is `__version__` in
`lib/dither.py`. Bump it together with a new section in this file when
releasing.


## [Unreleased]

_Nothing yet._


## [0.4.0] — 2026-05-11

### Added
- `effects.py` module with composable in-place transforms on grayscale
  buffers: `fade` (linear and exponential), `splat_point`, `splat_line`,
  `threshold`, `composite`. Designed as an optional pipeline stage
  between field generators and the dither layer.
- `Lissajous` curve sampler in `fields.py`. Parametric curve with seven
  built-in presets, slow per-frame drift, and `snap_period`-driven
  preset transitions.
- `TrailField` in `fields.py`. Stateful comet-trail field that composes
  `effects.fade` and `effects.splat_line` to draw decaying curves.
- `lissajous_demo.py`. Lissajous trail demo with mode/curve/fade cycling.

### Changed
- `fields.py` module docstring updated to distinguish stateless fields
  (Plasma, Metaballs, Tunnel) from stateful fields (TrailField).
- README expanded with a pipeline diagram and module list reflecting
  the new effects layer.


## [0.3.0] — 2026-05-11

### Added
- Blue noise dithering. `_blue_dither` viper kernel in `dither.py`,
  with matching CPython fallback.
- `blue_dither_to_xbm()` public function with lazy tile loading.
- `mode="blue"` branch in the `dither_to_xbm` dispatcher.
- `bluenoise_tile.py` — 64×64 CC0/public-domain threshold tile,
  generated locally by void-and-cluster (Ulichney 1993).
- `tools/generate_bluenoise.py` — the generator script. Run on host
  to regenerate the tile with different parameters.
- `dither_compare.py` upgraded to a 3-panel layout (FS / Bayer / Blue).

### Changed
- `plasma_demo.py` and `fields_demo.py` space-key behavior is now a
  3-way cycle (FS → Bayer → Blue → FS) instead of a 2-way toggle.
- Mode handling factored into a `MODES` tuple plus `_next_mode()` helper
  for clean extensibility.
- `dither_compare.py` default panel size reduced from 80 to 64 to
  comfortably fit three panels; `MAX_SIZE` clamp adjusted to 112.


## [0.2.0] — 2026-05-11

### Added
- `fields_demo.py` gallery. Cycle through Plasma / Metaballs / Tunnel
  with arrow keys; toggle dither mode with space.
- Args support on demos: pass field size and initial dither mode
  (`r plasma_demo 120 bayer`).

### Fixed
- `_fs_row` viper-vs-CPython mismatch. The previous `try/except`
  fallback only caught import-time errors; the shim's pass-through
  viper decorator succeeded at import but produced runtime
  `ValueError` when writing 16-bit values via `ptr16` (which is
  a byte-indexing identity function on CPython).
- Replaced exception-based fallback with explicit platform detection
  via `sys.implementation.name`. CPython uses `array.array('h', ...)`
  for error buffers; MicroPython uses bytearrays viewed as `ptr16`.


## [0.1.0] — 2026-05-09

### Added
- Initial package: `dither.py` with Floyd-Steinberg and Bayer dithering,
  `fields.py` with Plasma / Metaballs / Tunnel field generators.
- Two demo apps: `plasma_demo.py` (animated plasma with dither toggle)
  and `dither_compare.py` (FS vs Bayer side-by-side).
- Pure-MicroPython implementation; viper acceleration on device,
  CPython fallback for shim compatibility.
- README with module overview, field-size guidance, and design notes.


[Unreleased]: #unreleased
[0.4.0]: #040--2026-05-11
[0.3.0]: #030--2026-05-11
[0.2.0]: #020--2026-05-11
[0.1.0]: #010--2026-05-09
