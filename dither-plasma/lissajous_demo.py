# lissajous_demo.py
#
# Animated Lissajous curve drawn as a fading trail. Each frame:
#   1. The whole intensity buffer decays slightly (linear or exponential)
#   2. A new segment of the curve is stamped in at full brightness
#   3. The result is dithered for display
#
# The curve parameters morph slowly between snap-to-new-figure events,
# giving both continuous motion and rhythmic variety.
#
# Place in /sd/py and run with:  r lissajous_demo [size] [mode]
#
#   size:  field side length in pixels. Default 120.
#          Useful values: 60 (fast on shim), 120 (device default),
#          160, 200, 240 (full vertical).
#   mode:  initial dither mode, "fs", "bayer", or "blue". Default "blue".
#
# Examples:
#   r lissajous_demo              # 120x120, blue noise
#   r lissajous_demo 60           # 60x60 — fast shim iteration
#   r lissajous_demo 200 fs       # 200x200 with Floyd-Steinberg
#
# Controls:
#   Space               — cycle dither mode (FS / Bayer / Blue)
#   Right / Left arrow  — manually snap to next / previous curve preset
#   Up arrow            — toggle linear vs exponential fade
#   TP bottom-right     — quit

import time
import esclib as elib
from fields import Lissajous, TrailField, LISSAJOUS_PRESETS
from dither import draw_gray_rect

SCREEN_W = 400
SCREEN_H = 240

DEFAULT_SIZE = 120
DEFAULT_MODE = "blue"    # blue noise renders trail gradients most cleanly
MIN_SIZE = 32
MAX_SIZE = SCREEN_H

MODES = ("fs", "bayer", "blue")
FADE_MODES = ("linear", "exp")

# 4 seconds at ~60 fps = 240 frames. The TrailField docstring covers this
# in detail; this constant is the main knob to adjust trail length.
FADE_FRAMES = 240

# Snap to new curve preset every ~6 seconds. Long enough that the user
# sees the slow morph; short enough that the variety arrives regularly.
SNAP_PERIOD = 360


def _next_in(seq, current):
    """Cycle to the next item in a sequence, wrapping around."""
    i = seq.index(current) if current in seq else 0
    return seq[(i + 1) % len(seq)]


def _parse_args(args):
    size = DEFAULT_SIZE
    mode = DEFAULT_MODE

    if args is None:
        return size, mode

    if isinstance(args, str):
        parts = args.split()
    else:
        try:
            parts = [str(a) for a in args]
        except TypeError:
            parts = []

    if len(parts) >= 1:
        try:
            n = int(parts[0])
            if MIN_SIZE <= n <= MAX_SIZE:
                size = n
        except ValueError:
            pass

    if len(parts) >= 2:
        m = parts[1].lower()
        if m in MODES:
            mode = m

    return size, mode


class LissajousDemo:
    def __init__(self, v, size, mode):
        self.v = v
        self.w = size
        self.h = size
        self.x = (SCREEN_W - self.w) // 2
        self.y = (SCREEN_H - self.h) // 2

        # The curve sampler. Same sin_tab as Plasma uses, shared from fields.
        self.curve = Lissajous(self.w, self.h, snap_period=SNAP_PERIOD)
        self.mode = mode
        self.fade_mode = "linear"

        # The trail field wraps the curve, applies fade-then-stamp each
        # step, and returns the dither-ready grayscale buffer.
        self.trail = TrailField(
            self.w, self.h, self.curve,
            fade_frames=FADE_FRAMES,
            fade_mode=self.fade_mode,
            steps_per_frame=12,
            head_intensity=255,
        )

        self.last_us = time.ticks_us()
        self.fps = 0

    def _rebuild_trail(self):
        """Recreate the TrailField when fade_mode changes (re-derives
        per-frame decay amount from fade_frames + mode)."""
        self.trail = TrailField(
            self.w, self.h, self.curve,
            fade_frames=FADE_FRAMES,
            fade_mode=self.fade_mode,
            steps_per_frame=12,
            head_intensity=255,
        )

    def _handle_input(self):
        tpkey = self.v.get_tp_keys()
        if tpkey and tpkey[3] & 0x2 != 0:
            return True

        n, data = self.v.read_nb(16)
        if n <= 0:
            return False

        # read_nb returns str on device, bytes on shim. Normalize to bytes
        # so the comparisons below work on both platforms without
        # triggering MicroPython's bytes/str comparison warning.
        if isinstance(data, str):
            data = data.encode("ascii")

        i = 0
        while i < n:
            b = data[i:i+1]
            if b == b" ":
                self.mode = _next_in(MODES, self.mode)
                i += 1
            elif b == b"\x1b" and i + 2 < n:
                seq = data[i:i+3]
                if seq in (b"\x1b[C", b"\x1bOC"):       # right: next preset
                    self.curve.snap_next()
                elif seq in (b"\x1b[D", b"\x1bOD"):     # left: prev preset
                    self.curve.snap_prev()
                elif seq in (b"\x1b[A", b"\x1bOA"):     # up: toggle fade
                    self.fade_mode = _next_in(FADE_MODES, self.fade_mode)
                    self._rebuild_trail()
                i += 3
            else:
                i += 1
        return False

    def update(self, e):
        if not self.v.active:
            self.v.finished()
            return

        if self._handle_input():
            self.v.callback(None)
            return

        gray = self.trail.step()

        # Clear the field region. set_dither(16) ensures the clear is solid.
        self.v.set_dither(16)
        self.v.set_draw_color(0)
        self.v.draw_box(self.x, self.y, self.w, self.h)
        self.v.set_draw_color(1)

        draw_gray_rect(self.v, self.x, self.y, self.w, self.h,
                       gray, mode=self.mode)

        # Frame around the trail region
        self.v.draw_frame(self.x - 1, self.y - 1, self.w + 2, self.h + 2)

        # FPS
        now = time.ticks_us()
        diff = time.ticks_diff(now, self.last_us)
        self.last_us = now
        if diff > 0:
            self.fps = 1000000 // diff

        # HUD
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(4, 14,  "curve: " + self.curve.name)
        self.v.draw_str(4, 30,  "mode:  " + self.mode)
        self.v.draw_str(4, 46,  "fade:  " + self.fade_mode)
        self.v.draw_str(4, 62,  str(self.w) + "x" + str(self.h))
        self.v.draw_str(4, 78,  str(self.fps) + " fps")
        self.v.draw_str(4, 206, "[space] mode  [<-/->] curve")
        self.v.draw_str(4, 220, "[^] fade  [TP-BR] quit")

        self.v.finished()


def main(vs, args):
    size, mode = _parse_args(args)

    v = vs.v
    el = elib.esclib()
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    demo = LissajousDemo(v, size, mode)
    v.callback(demo.update)

    while v.callback_exists():
        time.sleep_ms(100)

    v.print(el.display_mode(True))
