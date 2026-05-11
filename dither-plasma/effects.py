# effects.py
#
# Composable in-place transforms on grayscale bytearrays. Each function
# operates on a `bytearray(w*h)` of 0..255 intensity values and either
# mutates it in place or writes into a provided destination buffer.
#
# These are designed as a pipeline stage between field generators
# (fields.py) and the dither layer (dither.py):
#
#     content_generator -> gray_buffer -> [effects...] -> dither -> xbm
#
# All kernels are @micropython.viper where worthwhile, with CPython
# fallbacks selected by sys.implementation.name (same pattern as
# dither.py).

import sys as _sys
_USE_VIPER = (getattr(_sys, "implementation", None) is not None
              and _sys.implementation.name == "micropython")


if _USE_VIPER:

    @micropython.viper
    def _fade_linear(gray, n: int, amount: int):
        # Subtract `amount` from every byte, saturating at 0.
        # This is the "trail decay" primitive — repeated application
        # shrinks intensities linearly until they hit zero.
        g = ptr8(gray)
        i: int = 0
        while i < n:
            v: int = int(g[i]) - amount
            if v < 0:
                v = 0
            g[i] = v
            i += 1

    @micropython.viper
    def _fade_exponential(gray, n: int, mul: int):
        # Multiply every byte by mul/256, rounding down. mul=240 gives
        # ~6% decay per frame; mul=224 gives ~12%; etc.
        # Exponential gives smooth phosphor-like fade vs linear's comet edge.
        g = ptr8(gray)
        i: int = 0
        while i < n:
            v: int = (int(g[i]) * mul) >> 8
            g[i] = v
            i += 1

    @micropython.viper
    def _splat_point(gray, w: int, h: int, x: int, y: int, intensity: int):
        # Set a single pixel to max(current, intensity). Out-of-bounds
        # silently clipped.
        if x < 0:
            return
        if x >= w:
            return
        if y < 0:
            return
        if y >= h:
            return
        g = ptr8(gray)
        idx: int = y * w + x
        if intensity > int(g[idx]):
            g[idx] = intensity

    @micropython.viper
    def _splat_line(gray, w: int, h: int,
                    x0: int, y0: int, x1: int, y1: int, intensity: int):
        # Bresenham line, writing max(current, intensity) at each pixel.
        # Lines are how trails accumulate continuous curves — successive
        # sample points get joined so motion is smooth, not pointillist.
        g = ptr8(gray)

        dx: int = x1 - x0
        if dx < 0:
            dx = -dx
        dy: int = y1 - y0
        if dy < 0:
            dy = -dy

        sx: int = 1 if x0 < x1 else -1
        sy: int = 1 if y0 < y1 else -1

        err: int = dx - dy
        x: int = x0
        y: int = y0

        while True:
            if x >= 0:
                if x < w:
                    if y >= 0:
                        if y < h:
                            idx: int = y * w + x
                            if intensity > int(g[idx]):
                                g[idx] = intensity
            if x == x1:
                if y == y1:
                    return
            e2: int = err << 1
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    @micropython.viper
    def _threshold_linear(gray, n: int, lo: int, hi: int):
        # Remap input range [lo, hi] to output [0, 255], clamping outside.
        # Useful before dithering to punch up midtones or kill near-black noise.
        g = ptr8(gray)
        span: int = hi - lo
        if span <= 0:
            return
        i: int = 0
        while i < n:
            v: int = int(g[i]) - lo
            if v <= 0:
                v = 0
            elif v >= span:
                v = 255
            else:
                v = (v * 255) // span
            g[i] = v
            i += 1

    @micropython.viper
    def _composite_max(dst, src, n: int):
        # dst[i] = max(dst[i], src[i]) — "lighten" composite mode
        d = ptr8(dst)
        s = ptr8(src)
        i: int = 0
        while i < n:
            sv: int = int(s[i])
            if sv > int(d[i]):
                d[i] = sv
            i += 1

    @micropython.viper
    def _composite_add(dst, src, n: int):
        # dst[i] = clamp(dst[i] + src[i], 0, 255) — additive blend
        d = ptr8(dst)
        s = ptr8(src)
        i: int = 0
        while i < n:
            v: int = int(d[i]) + int(s[i])
            if v > 255:
                v = 255
            d[i] = v
            i += 1

else:
    # CPython fallbacks. Same semantics, slower.

    def _fade_linear(gray, n, amount):
        for i in range(n):
            v = gray[i] - amount
            gray[i] = 0 if v < 0 else v

    def _fade_exponential(gray, n, mul):
        for i in range(n):
            gray[i] = (gray[i] * mul) >> 8

    def _splat_point(gray, w, h, x, y, intensity):
        if 0 <= x < w and 0 <= y < h:
            idx = y * w + x
            if intensity > gray[idx]:
                gray[idx] = intensity

    def _splat_line(gray, w, h, x0, y0, x1, y1, intensity):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            if 0 <= x < w and 0 <= y < h:
                idx = y * w + x
                if intensity > gray[idx]:
                    gray[idx] = intensity
            if x == x1 and y == y1:
                return
            e2 = err << 1
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def _threshold_linear(gray, n, lo, hi):
        span = hi - lo
        if span <= 0:
            return
        for i in range(n):
            v = gray[i] - lo
            if v <= 0:
                gray[i] = 0
            elif v >= span:
                gray[i] = 255
            else:
                gray[i] = (v * 255) // span

    def _composite_max(dst, src, n):
        for i in range(n):
            if src[i] > dst[i]:
                dst[i] = src[i]

    def _composite_add(dst, src, n):
        for i in range(n):
            v = dst[i] + src[i]
            dst[i] = 255 if v > 255 else v


# Public API — thin wrappers that pass length explicitly so callers
# don't need to recompute it.

def fade(gray, w, h, amount=4, mode="linear"):
    """Decay every pixel toward zero.

    mode="linear":  subtract `amount` per pixel, saturating at 0.
                    Comet-trail look with hard tail edge.
                    `amount` is the per-call decrement (e.g. 4 over
                    64 frames takes a 255 pixel to ~0).

    mode="exp":     multiply every pixel by (256 - amount) / 256.
                    Phosphor-fade look, asymptotic decay.
                    `amount` is the per-call decay step (e.g. 16
                    means each call retains ~94% of intensity).
    """
    n = w * h
    if mode == "linear":
        _fade_linear(gray, n, amount)
    elif mode == "exp":
        _fade_exponential(gray, n, 256 - amount)
    else:
        raise ValueError("fade mode must be 'linear' or 'exp'")


def splat_point(gray, w, h, x, y, intensity=255):
    """Set a single pixel to max(current, intensity). Out-of-bounds OK."""
    _splat_point(gray, w, h, int(x), int(y), int(intensity))


def splat_line(gray, w, h, x0, y0, x1, y1, intensity=255):
    """Bresenham line from (x0,y0) to (x1,y1), writing max(current, intensity)
    at each pixel. Out-of-bounds OK. Use this for continuous curves —
    successive sample points joined into a connected trail."""
    _splat_line(gray, w, h,
                int(x0), int(y0), int(x1), int(y1), int(intensity))


def threshold(gray, w, h, lo=0, hi=255):
    """Linearly remap input range [lo, hi] to output [0, 255], clamping
    outside. lo > hi inverts. Use before dither to:
    - Punch contrast (lo=64, hi=192 expands midtones to full range)
    - Kill faint trail residue (lo=20, hi=255 maps faint to black)
    - Invert (lo=255, hi=0)
    """
    _threshold_linear(gray, w * h, lo, hi)


def composite(dst, src, w, h, mode="max"):
    """Blend src into dst in place.

    mode="max": dst = max(dst, src) — "lighten" / additive max
    mode="add": dst = clamp(dst + src, 0, 255) — additive with clip

    Used to layer effects: render two field sources independently,
    then composite. Both buffers must be the same size.
    """
    n = w * h
    if mode == "max":
        _composite_max(dst, src, n)
    elif mode == "add":
        _composite_add(dst, src, n)
    else:
        raise ValueError("composite mode must be 'max' or 'add'")
