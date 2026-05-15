# fields_demo.py
#
# Gallery of all the field generators in fields.py. Cycles through
# Plasma, Metaballs, and Tunnel; each renders through whichever dither
# mode you've selected.
#
# Place in /sd/py and run with:  r fields_demo [size] [mode]
#
#   size:  field side length in pixels. Default 80.
#          Useful values: 40 (fast on shim), 80 (device default),
#          120, 160 (larger panels), max 240.
#   mode:  initial dither mode, "fs" or "bayer". Default "fs".
#
# Examples:
#   r fields_demo              # 80x80, FS
#   r fields_demo 40           # 40x40, FS — fast shim iteration
#   r fields_demo 120 bayer    # 120x120, Bayer
#
# Controls:
#   Right / Left arrow  — next / previous field
#   Space               — toggle FS / Bayer dither mode
#   TP bottom-right     — quit

import time
import esclib as elib
from fields import Plasma, Metaballs, Tunnel
from dither import draw_gray_rect

SCREEN_W = 400
SCREEN_H = 240

DEFAULT_SIZE = 80
DEFAULT_MODE = "fs"
MIN_SIZE = 16
MAX_SIZE = SCREEN_H

# Dither modes cycled by space key. Adding a new mode? Add it in dither.py
# and append it here.
MODES = ("fs", "bayer", "blue")


def _next_mode(current):
    i = MODES.index(current) if current in MODES else 0
    return MODES[(i + 1) % len(MODES)]

# Field registry: (display name, factory). Each factory takes (w, h) and
# returns an object with a .step() method returning a grayscale bytearray.
# Adding a new field is one line — define it in fields.py, then append a
# tuple here.
FIELD_REGISTRY = [
    ("plasma",    lambda w, h: Plasma(w, h)),
    ("metaballs", lambda w, h: Metaballs(w, h, n=3, strength=96)),
    ("tunnel",    lambda w, h: Tunnel(w, h, speed=3)),
]


def _parse_args(args):
    """Same parser shape as the other demos: (size, mode), defensive
    against None / list / string / bad input."""
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


class FieldsDemo:
    def __init__(self, v, size, mode):
        self.v = v
        self.w = size
        self.h = size
        self.x = (SCREEN_W - self.w) // 2
        self.y = (SCREEN_H - self.h) // 2

        # Pre-instantiate all fields so switching is instant. Each holds
        # its own state (frame counter, precomputed tables, gray buffer)
        # so cycling between them resumes where they left off — gives a
        # nice continuity instead of restarting the animation.
        self.fields = [(name, factory(self.w, self.h))
                       for name, factory in FIELD_REGISTRY]
        self.field_idx = 0
        self.mode = mode

        self.last_us = time.ticks_us()
        self.fps = 0

    def _current_name_and_field(self):
        return self.fields[self.field_idx]

    def _cycle_field(self, delta):
        self.field_idx = (self.field_idx + delta) % len(self.fields)

    def _handle_input(self):
        """Read pending keyboard bytes and dispatch.

        Arrow keys arrive as 3-byte escape sequences (\x1b[A etc), so we
        read a chunk big enough to hold a few of them. The deck terminal
        may also send rawmode-style \x1bOA — we accept both.

        Returns True if the demo should quit.
        """
        # TP bottom-right always quits, regardless of keyboard state
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

        # Walk the input bytes. Escape sequences are 3 bytes; everything
        # else is single-byte. We don't try to reassemble across read
        # boundaries — for an interactive UI this is fine.
        i = 0
        while i < n:
            b = data[i:i+1]
            if b == b" ":
                self.mode = _next_mode(self.mode)
                i += 1
            elif b == b"\x1b" and i + 2 < n:
                seq = data[i:i+3]
                if seq in (b"\x1b[C", b"\x1bOC"):       # right
                    self._cycle_field(+1)
                elif seq in (b"\x1b[D", b"\x1bOD"):     # left
                    self._cycle_field(-1)
                # up/down currently unused but harmless
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

        name, field = self._current_name_and_field()
        gray = field.step()

        # Clear the field region. set_dither(16) ensures a solid clear
        # regardless of any leftover dither state from previous draws.
        self.v.set_dither(16)
        self.v.set_draw_color(0)
        self.v.draw_box(self.x, self.y, self.w, self.h)
        self.v.set_draw_color(1)

        # Dither and blit
        draw_gray_rect(self.v, self.x, self.y, self.w, self.h,
                       gray, mode=self.mode)

        # Frame around the field for visual definition
        self.v.draw_frame(self.x - 1, self.y - 1, self.w + 2, self.h + 2)

        # FPS
        now = time.ticks_us()
        diff = time.ticks_diff(now, self.last_us)
        self.last_us = now
        if diff > 0:
            self.fps = 1000000 // diff

        # HUD
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(4, 14,  "field: " + name)
        self.v.draw_str(4, 30,  "mode:  " + self.mode)
        self.v.draw_str(4, 46,  str(self.w) + "x" + str(self.h))
        self.v.draw_str(4, 62,  str(self.fps) + " fps")
        self.v.draw_str(4, 220, "[<-/->] field  [space] mode")
        self.v.draw_str(4, 234, "[TP-BR] quit")

        self.v.finished()


def main(vs, args):
    size, mode = _parse_args(args)

    v = vs.v
    el = elib.esclib()
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    demo = FieldsDemo(v, size, mode)
    v.callback(demo.update)

    while v.callback_exists():
        time.sleep_ms(100)

    v.print(el.display_mode(True))
