# dither.py
#
# Pure-MicroPython dithering for the Pocket Deck.
# Converts 8-bit grayscale bytearrays into 1-bit XBM buffers suitable for
# v.draw_xbm(). Provides Floyd-Steinberg (error-diffusion) and Bayer
# (ordered) algorithms, plus convenience primitives that combine the
# dither step with the final blit.
#
# XBM output is MSB-first packed (8 pixels per byte), matching the format
# expected by vscreen.draw_xbm and produced by pngreader.py.
#
# Usage:
#   from dither import draw_gray_rect
#   gray = bytearray(w * h)   # fill with 0..255 intensity values
#   draw_gray_rect(v, 40, 40, w, h, gray, mode="fs")

# 4x4 Bayer ordered dither matrix (threshold values 0..255).
# Same matrix used in pngreader.py so results are consistent.
_BAYER = bytes([
      0, 128,  32, 160,
    192,  64, 224,  96,
     48, 176,  16, 144,
    240, 112, 208,  80,
])


# Platform detection: real MicroPython has a `micropython` module with
# `mem_info` (an attribute that doesn't exist on the CPython shim's
# pass-through stub). We use that to decide whether to install the
# viper-accelerated kernels (correct on device) or the plain-Python
# kernels (correct on CPython under the shim).
#
# Why not just use `try: viper... except: fallback`? Because the shim's
# @micropython.viper is a pass-through identity decorator that succeeds
# at import time but produces functions that misbehave at runtime — they
# assume ptr16 indexing semantics that bytearrays don't actually provide
# on CPython. We need a real branch, not an exception guard.

def _is_real_micropython():
    try:
        import micropython
        return hasattr(micropython, "mem_info")
    except ImportError:
        return False


_USE_VIPER = _is_real_micropython()


if _USE_VIPER:
    # Viper-accelerated kernels. These are the hot paths on the device.
    # ec/en are bytearrays of size 2*(w+2), reinterpreted as uint16 arrays
    # via ptr16 — this is a viper compiler intrinsic.

    @micropython.viper
    def _bayer_dither(gray, xbm, w: int, h: int, bayer):
        # Stateless threshold per pixel against the Bayer matrix.
        # Output is MSB-first packed.
        g  = ptr8(gray)
        x8 = ptr8(xbm)
        b  = ptr8(bayer)
        xs: int = (w + 7) >> 3

        y: int = 0
        while y < h:
            by: int = (y & 3) << 2
            xr: int = y * xs
            gr: int = y * w
            x: int = 0
            while x < w:
                if int(g[gr + x]) > int(b[by + (x & 3)]):
                    x8[xr + (x >> 3)] = int(x8[xr + (x >> 3)]) | (0x80 >> (x & 7))
                x += 1
            y += 1

    @micropython.viper
    def _fs_row(gray_row, xbm_row, w: int, ec, en):
        # Single row of Floyd-Steinberg dithering.
        # gray_row: ptr8 to this row's grayscale values (w bytes)
        # xbm_row:  ptr8 to this row's XBM output (must be pre-zeroed)
        # ec: ptr to current row's error buffer, int16 with 1-pixel guard each side
        #     (length w+2 int16s; index x+1 is the error for pixel x)
        # en: ptr to next row's error buffer, same layout, must be zeroed on entry
        g  = ptr8(gray_row)
        x8 = ptr8(xbm_row)
        c  = ptr16(ec)
        n  = ptr16(en)

        x: int = 0
        while x < w:
            # Read current error, sign-extend from uint16
            e: int = int(c[x + 1])
            if e >= 32768:
                e -= 65536

            old: int = int(g[x]) + e
            # Threshold at 128
            if old >= 128:
                new: int = 255
                x8[x >> 3] = int(x8[x >> 3]) | (0x80 >> (x & 7))
            else:
                new: int = 0
            err: int = old - new

            # Distribute: 7/16 right, 3/16 down-left, 5/16 down, 1/16 down-right
            e7: int = (err * 7) >> 4
            e3: int = (err * 3) >> 4
            e5: int = (err * 5) >> 4
            e1: int = err >> 4

            # right: ec[x+2]
            v: int = int(c[x + 2])
            if v >= 32768:
                v -= 65536
            v += e7
            c[x + 2] = v & 0xFFFF

            # down-left: en[x]
            v = int(n[x])
            if v >= 32768:
                v -= 65536
            v += e3
            n[x] = v & 0xFFFF

            # down: en[x+1]
            v = int(n[x + 1])
            if v >= 32768:
                v -= 65536
            v += e5
            n[x + 1] = v & 0xFFFF

            # down-right: en[x+2]
            v = int(n[x + 2])
            if v >= 32768:
                v -= 65536
            v += e1
            n[x + 2] = v & 0xFFFF

            x += 1

    @micropython.viper
    def _zero16(buf, count: int):
        # Zero a uint16 buffer. Used to clear the "next row" error
        # accumulator between rows of FS processing.
        p = ptr16(buf)
        i: int = 0
        while i < count:
            p[i] = 0
            i += 1

    def _make_err_buf(w):
        # Device path uses bytearrays viewed as ptr16 inside _fs_row.
        # 2 bytes per int16 element, plus 2 guard slots (one each side).
        return bytearray(2 * (w + 2))

else:
    # CPython / shim path. Used when running under pdeck_sim or any
    # other non-MicroPython host. Slower but produces identical pixel
    # output, so visual parity with the device is preserved for
    # development workflows.
    #
    # Key difference from the viper version: the error buffers are
    # array.array('h', ...) (signed int16) rather than bytearrays
    # reinterpreted via ptr16. This makes indexing semantics natural
    # in CPython — c[i] reads/writes one int16 element, not one byte.

    import array as _array

    def _bayer_dither(gray, xbm, w, h, bayer):
        xs = (w + 7) >> 3
        for y in range(h):
            by = (y & 3) << 2
            xr = y * xs
            gr = y * w
            for x in range(w):
                if gray[gr + x] > bayer[by + (x & 3)]:
                    xbm[xr + (x >> 3)] |= 0x80 >> (x & 7)

    def _fs_row(gray_row, xbm_row, w, ec, en):
        # ec and en are array.array('h') signed-int16 arrays of
        # length w+2. Index x+1 holds the error for pixel x; index 0
        # and index w+1 are guard slots so we can write left/right
        # neighbors without bounds checks.
        for x in range(w):
            e = ec[x + 1]
            old = gray_row[x] + e
            if old >= 128:
                new = 255
                xbm_row[x >> 3] |= 0x80 >> (x & 7)
            else:
                new = 0
            err = old - new
            # Floyd-Steinberg distribution: 7/16 right, 3/16 dl, 5/16 d, 1/16 dr
            ec[x + 2] += (err * 7) >> 4
            en[x]     += (err * 3) >> 4
            en[x + 1] += (err * 5) >> 4
            en[x + 2] += err >> 4

    def _zero16(buf, count):
        # Zero an int16 array (or bytearray viewed as such).
        for i in range(count):
            buf[i] = 0


    def _make_err_buf(w):
        # CPython path uses array.array('h') for proper signed int16
        # indexing semantics. Length is w+2 (one guard slot at each end).
        return _array.array('h', [0] * (w + 2))


def bayer_dither_to_xbm(gray, w, h):
    """Convert an 8-bit grayscale bytearray to a 1-bit MSB-first XBM buffer
    using a 4x4 Bayer ordered dither matrix.

    Returns a bytearray of length ((w + 7) // 8) * h, ready to pass to
    vscreen.draw_xbm().

    gray: bytearray of length w * h, values 0..255
    """
    xs = (w + 7) >> 3
    xbm = bytearray(xs * h)
    _bayer_dither(gray, xbm, w, h, _BAYER)
    return xbm


def fs_dither_to_xbm(gray, w, h, err_a=None, err_b=None):
    """Convert an 8-bit grayscale bytearray to a 1-bit MSB-first XBM buffer
    using Floyd-Steinberg error diffusion.

    Slower than Bayer but produces organic, less patterned output. Good for
    images and smooth fields where Bayer's crosshatch would be visible.

    err_a, err_b: optional pre-allocated int16 error buffers. If None,
        they are allocated per call. For repeated dithering at the same
        width, pass cached buffers (use _make_err_buf(w)) to avoid
        allocation churn.

        On the device these are bytearray(2 * (w + 2)) viewed as ptr16.
        On CPython they are array.array('h', [0]*(w+2)). The
        _make_err_buf helper produces the right type for the platform.
    """
    xs = (w + 7) >> 3
    xbm = bytearray(xs * h)

    if err_a is None:
        err_a = _make_err_buf(w)
    if err_b is None:
        err_b = _make_err_buf(w)

    # Clear current-row error (may have residue from previous call)
    _zero16(err_a, w + 2)

    # Alternate ec/en per row using a flag rather than swapping the names,
    # since viper function arguments can't easily be rebound.
    flip = False
    for y in range(h):
        gray_row_off = y * w
        xbm_row_off = y * xs
        # Create memoryviews for this row so viper sees them as ptr8
        gray_row = memoryview(gray)[gray_row_off:gray_row_off + w]
        xbm_row  = memoryview(xbm)[xbm_row_off:xbm_row_off + xs]

        if flip:
            ec, en = err_b, err_a
        else:
            ec, en = err_a, err_b

        # Zero the "next row" error accumulator before distributing into it
        _zero16(en, w + 2)

        _fs_row(gray_row, xbm_row, w, ec, en)

        flip = not flip

    return xbm


def dither_to_xbm(gray, w, h, mode="fs"):
    """Dispatch to the requested dither algorithm.

    mode: "fs" for Floyd-Steinberg, "bayer" for Bayer ordered dither.
    """
    if mode == "fs":
        return fs_dither_to_xbm(gray, w, h)
    elif mode == "bayer":
        return bayer_dither_to_xbm(gray, w, h)
    else:
        raise ValueError("unknown dither mode: " + repr(mode))


def draw_gray_rect(v, x, y, w, h, gray, mode="fs"):
    """Dither a grayscale bytearray and blit it to the vscreen at (x, y).

    This is the main entry point most callers want. The grayscale buffer
    can come from anywhere: an image decoder, a gradient fill, a plasma
    field, etc.

    v:    vscreen object (from vs.v or pdeck.vscreen())
    x, y: top-left coordinates on screen
    w, h: dimensions of the grayscale region
    gray: bytearray of length w * h, 0..255 intensity
    mode: "fs" or "bayer"
    """
    xbm = dither_to_xbm(gray, w, h, mode=mode)
    v.draw_xbm(x, y, w, h, xbm)


def draw_field(v, x, y, w, h, field_fn, t, mode="fs", gray_buf=None):
    """Generate a field via field_fn and blit it dithered.

    field_fn(gray, w, h, t) is called to fill the grayscale buffer.
    This is a thin convenience wrapper; callers with their own field
    classes (see fields.py) can skip it and call draw_gray_rect directly.

    gray_buf: optional pre-allocated bytearray of size w*h to reuse
        across frames. Strongly recommended for animation to avoid GC
        churn.
    """
    if gray_buf is None:
        gray_buf = bytearray(w * h)
    field_fn(gray_buf, w, h, t)
    draw_gray_rect(v, x, y, w, h, gray_buf, mode=mode)


# Fill helpers for common intensity patterns. These produce grayscale
# input you can feed to draw_gray_rect. They're here in dither.py rather
# than fields.py because they're static (not time-varying) and closely
# related to the dither primitives.

try:
    @micropython.viper
    def _fill_gradient_v(gray, w: int, h: int, g0: int, g1: int):
        # Vertical linear gradient from g0 (top) to g1 (bottom).
        g = ptr8(gray)
        y: int = 0
        while y < h:
            # Fixed-point lerp: value = g0 + (g1-g0) * y / (h-1)
            if h > 1:
                v: int = g0 + ((g1 - g0) * y) // (h - 1)
            else:
                v = g0
            row: int = y * w
            x: int = 0
            while x < w:
                g[row + x] = v & 0xFF
                x += 1
            y += 1

    @micropython.viper
    def _fill_gradient_h(gray, w: int, h: int, g0: int, g1: int):
        # Horizontal linear gradient from g0 (left) to g1 (right).
        g = ptr8(gray)
        y: int = 0
        while y < h:
            row: int = y * w
            x: int = 0
            while x < w:
                if w > 1:
                    v: int = g0 + ((g1 - g0) * x) // (w - 1)
                else:
                    v = g0
                g[row + x] = v & 0xFF
                x += 1
            y += 1

except Exception:
    def _fill_gradient_v(gray, w, h, g0, g1):
        for y in range(h):
            v = g0 + ((g1 - g0) * y) // max(1, h - 1)
            for x in range(w):
                gray[y * w + x] = v & 0xFF

    def _fill_gradient_h(gray, w, h, g0, g1):
        for y in range(h):
            for x in range(w):
                v = g0 + ((g1 - g0) * x) // max(1, w - 1)
                gray[y * w + x] = v & 0xFF


def draw_gradient_box(v, x, y, w, h, g0, g1, direction="v", mode="fs"):
    """Draw a dithered linear gradient box.

    direction: "v" for top-to-bottom, "h" for left-to-right
    g0, g1:    start and end intensities, 0..255
    """
    gray = bytearray(w * h)
    if direction == "v":
        _fill_gradient_v(gray, w, h, g0, g1)
    elif direction == "h":
        _fill_gradient_h(gray, w, h, g0, g1)
    else:
        raise ValueError("direction must be 'v' or 'h'")
    draw_gray_rect(v, x, y, w, h, gray, mode=mode)
