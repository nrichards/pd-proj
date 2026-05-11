# dither_compare.py
#
# Three-panel comparison of Floyd-Steinberg, Bayer, and blue noise
# dithering on the same plasma field. All three panels share the same
# grayscale source per frame, so any visual difference is purely the
# dither algorithm.
#
# Place in /sd/py and run with:  r dither_compare [size]
#
#   size:  panel side length in pixels. Default 64.
#          Three panels of this size sit side by side with gaps.
#          Useful values: 32 (fast on shim), 64 (device default),
#          80, 100 (largest that still fits with margins).
#
# Examples:
#   r dither_compare         # 64x64 panels
#   r dither_compare 32      # 32x32 — fast shim iteration
#   r dither_compare 80      # 80x80 — biggest practical at 3-up
#
# Touch the bottom-right button to exit.

import time
import esclib as elib
from fields import Plasma
from dither import draw_gray_rect

SCREEN_W = 400
SCREEN_H = 240
GAP = 12
N_PANELS = 3

DEFAULT_SIZE = 64

# Clamp so three panels plus two gaps fit horizontally with margin to spare.
# 3*W + 2*GAP must fit in SCREEN_W with at least 20px on each side.
MIN_SIZE = 16
MAX_SIZE = (SCREEN_W - 2 * GAP - 40) // 3   # = 112 for the defaults above

PANELS = (
    ("fs",    "FS"),
    ("bayer", "Bayer"),
    ("blue",  "Blue"),
)


def _parse_args(args):
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

        # Compute panel x-positions: three panels centered together with
        # GAP between them. Layout: [margin][P0][gap][P1][gap][P2][margin]
        total_w = N_PANELS * self.w + (N_PANELS - 1) * GAP
        first_x = (SCREEN_W - total_w) // 2
        self.xs = [first_x + i * (self.w + GAP) for i in range(N_PANELS)]
        # Vertical position leaves room for labels above and HUD below
        self.y = (SCREEN_H - self.h) // 2

        # One plasma generator drives all three panels so the visual
        # difference is purely algorithmic.
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

        # One field, three renders
        gray = self.plasma.step()

        # Clear all panel regions before redrawing
        self.v.set_dither(16)
        self.v.set_draw_color(0)
        for x in self.xs:
            self.v.draw_box(x, self.y, self.w, self.h)
        self.v.set_draw_color(1)

        # Render each panel through its respective dither mode
        for x, (mode, _) in zip(self.xs, PANELS):
            draw_gray_rect(self.v, x, self.y, self.w, self.h,
                           gray, mode=mode)

        # Labels above each panel and frames around them
        self.v.set_font("u8g2_font_profont15_mf")
        for x, (_, label) in zip(self.xs, PANELS):
            self.v.draw_str(x, self.y - 6, label)
            self.v.draw_frame(x - 1, self.y - 1, self.w + 2, self.h + 2)

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
