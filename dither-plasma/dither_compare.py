# dither_compare.py
#
# Side-by-side comparison of Floyd-Steinberg vs Bayer dithering on the
# same plasma field. Left half is FS, right half is Bayer, sharing the
# same grayscale source per frame — so any visual difference is purely
# the dither algorithm.
#
# Place in /sd/py and run with:  r dither_compare [size]
#
#   size:  panel side length in pixels. Default 80.
#          Two panels of this size sit side by side with a small gap.
#          Useful values: 40 (fast on shim), 80 (device default),
#          100, 120 (largest that fits comfortably with labels).
#
# Examples:
#   r dither_compare         # 80x80 panels
#   r dither_compare 40      # 40x40 — fast shim iteration
#   r dither_compare 120     # 120x120 — biggest practical comparison
#
# Touch the bottom-right button to exit.

import time
import esclib as elib
from fields import Plasma
from dither import draw_gray_rect

SCREEN_W = 400
SCREEN_H = 240
GAP = 20

DEFAULT_SIZE = 80

# Clamp so two panels plus the gap fit horizontally with margin to spare.
# Two panels + gap must fit in SCREEN_W with at least 20px on each side.
MIN_SIZE = 16
MAX_SIZE = (SCREEN_W - GAP - 40) // 2  # = 170


def _parse_args(args):
    """Pull panel size from args; fall back to default on bad input."""
    if args is None:
        return DEFAULT_SIZE

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
                return n
        except ValueError:
            pass

    return DEFAULT_SIZE


class DitherCompare:
    def __init__(self, v, size):
        self.v = v
        self.w = size
        self.h = size

        # Two panels centered together with the gap between them
        total_w = 2 * self.w + GAP
        self.left_x  = (SCREEN_W - total_w) // 2
        self.right_x = self.left_x + self.w + GAP
        # Panel y leaves room for labels above
        self.y = (SCREEN_H - self.h) // 2

        # One plasma generator; both panels render its output through
        # different dither algorithms.
        self.plasma = Plasma(self.w, self.h)
        self.last_us = time.ticks_us()
        self.fps = 0

    def update(self, e):
        if not self.v.active:
            self.v.finished()
            return

        tpkey = self.v.get_tp_keys()
        if tpkey and tpkey[3] & 0x2 != 0:
            self.v.callback(None)
            return

        # One field, two renders
        gray = self.plasma.step()

        # Clear both panel regions before redrawing
        self.v.set_dither(16)
        self.v.set_draw_color(0)
        self.v.draw_box(self.left_x,  self.y, self.w, self.h)
        self.v.draw_box(self.right_x, self.y, self.w, self.h)
        self.v.set_draw_color(1)

        # Left: Floyd-Steinberg
        draw_gray_rect(self.v, self.left_x, self.y, self.w, self.h,
                       gray, mode="fs")

        # Right: Bayer
        draw_gray_rect(self.v, self.right_x, self.y, self.w, self.h,
                       gray, mode="bayer")

        # Labels above each panel
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(self.left_x,  self.y - 6, "floyd-steinberg")
        self.v.draw_str(self.right_x, self.y - 6, "bayer 4x4")

        # Frames outline each panel for visual separation
        self.v.draw_frame(self.left_x  - 1, self.y - 1,
                          self.w + 2, self.h + 2)
        self.v.draw_frame(self.right_x - 1, self.y - 1,
                          self.w + 2, self.h + 2)

        # FPS and size readout in the top-left corner
        now = time.ticks_us()
        diff = time.ticks_diff(now, self.last_us)
        self.last_us = now
        if diff > 0:
            self.fps = 1000000 // diff
        self.v.draw_str(4, 14, str(self.w) + "x" + str(self.h))
        self.v.draw_str(4, 30, str(self.fps) + " fps")
        self.v.draw_str(4, 230, "[TP-BR] quit")

        self.v.finished()


def main(vs, args):
    size = _parse_args(args)

    v = vs.v
    el = elib.esclib()
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    demo = DitherCompare(v, size)
    v.callback(demo.update)

    while v.callback_exists():
        time.sleep_ms(100)

    v.print(el.display_mode(True))
