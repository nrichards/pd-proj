# plasma_demo.py
#
# Animated plasma field dithered to the Pocket Deck's 1-bit screen.
# Place in /sd/py and run with:  r plasma_demo [size] [mode]
#
#   size:  field side length in pixels. Default 80.
#          Useful values: 40 (fast on shim), 80 (device default),
#          120, 160 (larger panels), max 240 (square clips).
#   mode:  initial dither mode, "fs" or "bayer". Default "fs".
#          Toggle live with space.
#
# Examples:
#   r plasma_demo            # 80x80, FS
#   r plasma_demo 40         # 40x40, FS — fast shim iteration
#   r plasma_demo 120 bayer  # 120x120, Bayer — bigger panel, ordered dither
#
# Touch the bottom-right button to exit.

import time
import esclib as elib
from fields import Plasma
from dither import draw_gray_rect

# Screen geometry
SCREEN_W = 400
SCREEN_H = 240

# Defaults applied when args are missing or malformed
DEFAULT_SIZE = 120
DEFAULT_MODE = "fs"

# Clamps. Field is square, so the height limit (240) bounds it.
MIN_SIZE = 16
MAX_SIZE = SCREEN_H


def _parse_args(args):
    """Pull (size, mode) from the args list passed to main().

    The Pocket Deck's `r` runner forwards space-separated arguments as a
    list of strings. Both args are optional and order-sensitive: size
    first, mode second. Bad input falls back to defaults rather than
    erroring — easier to recover from in interactive use.
    """
    size = DEFAULT_SIZE
    mode = DEFAULT_MODE

    if args is None:
        return size, mode

    # Defensive: args might be a list, tuple, or string on different
    # runner versions. Coerce to list-of-strings.
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
        if m in ("fs", "bayer"):
            mode = m

    return size, mode


class PlasmaDemo:
    def __init__(self, v, size, mode):
        self.v = v
        self.w = size
        self.h = size
        # Center the field on screen
        self.x = (SCREEN_W - self.w) // 2
        self.y = (SCREEN_H - self.h) // 2

        self.plasma = Plasma(self.w, self.h)
        self.mode = mode
        self.last_us = time.ticks_us()
        self.fps = 0

    def update(self, e):
        if not self.v.active:
            self.v.finished()
            return

        # TP bottom-right quits
        tpkey = self.v.get_tp_keys()
        if tpkey and tpkey[3] & 0x2 != 0:
            self.v.callback(None)
            return

        # Space key toggles dither mode
        n, data = self.v.read_nb(4)
        if n > 0 and b" " in data:
            self.mode = "bayer" if self.mode == "fs" else "fs"

        # Advance one frame of the field
        gray = self.plasma.step()

        # Clear the field region. set_dither(16) ensures we draw a solid
        # black box (no Bayer screening on the clear itself).
        self.v.set_dither(16)
        self.v.set_draw_color(0)
        self.v.draw_box(self.x, self.y, self.w, self.h)
        self.v.set_draw_color(1)

        # Dither and blit
        draw_gray_rect(self.v, self.x, self.y, self.w, self.h,
                       gray, mode=self.mode)

        # FPS counter and mode indicator
        now = time.ticks_us()
        diff = time.ticks_diff(now, self.last_us)
        self.last_us = now
        if diff > 0:
            self.fps = 1000000 // diff

        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(4, 14, "mode: " + self.mode)
        self.v.draw_str(4, 30, str(self.w) + "x" + str(self.h))
        self.v.draw_str(4, 46, str(self.fps) + " fps")
        self.v.draw_str(4, 230, "[space] toggle  [TP-BR] quit")

        self.v.finished()


def main(vs, args):
    size, mode = _parse_args(args)

    v = vs.v
    el = elib.esclib()
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    demo = PlasmaDemo(v, size, mode)
    v.callback(demo.update)

    while v.callback_exists():
        time.sleep_ms(100)

    v.print(el.display_mode(True))
