# fields.py
#
# Animated grayscale field generators for the Pocket Deck, intended to be
# paired with dither.py for display on the 1-bit screen.
#
# Each field class exposes a .step() method returning a grayscale bytearray
# (0..255) of shape w*h. The caller is responsible for dithering and
# blitting; see demos/plasma_demo.py for usage.
#
# Stateless fields (Plasma, Metaballs, Tunnel) regenerate their buffer
# from scratch each frame based on a time/frame counter. Stateful fields
# (TrailField) maintain a persistent buffer across frames and apply
# in-place transformations from effects.py — this is the pattern for
# fades, trails, smoke, and other "history-dependent" visuals.
#
# All kernels are @micropython.viper for speed. Tables are precomputed
# once at construction and reused every frame.

import math


def _build_sin_tab_128():
    """Build a 256-entry signed-sin table encoded as unsigned bytes.

    Each entry is sin(2*pi * i/256) * 127, offset by +128 so it fits in
    a uint8. To recover signed: int(tab[i]) - 128, giving range -128..127.
    """
    tab = bytearray(256)
    for i in range(256):
        v = int(math.sin(2.0 * math.pi * i / 256.0) * 127.0)
        tab[i] = (v + 128) & 0xFF
    return tab


def _build_radial_tab(w, h):
    """Build a w*h table of sqrt((x-cx)^2 + (y-cy)^2), scaled to fit
    in a byte (0..255). Used as phase into the sin table for the
    radial term of plasma.
    """
    cx = w / 2.0
    cy = h / 2.0
    # Scale so that the corner distance maps to ~255
    max_d = math.sqrt(cx * cx + cy * cy)
    scale = 255.0 / max_d if max_d > 0 else 0.0

    tab = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d = math.sqrt(dx * dx + dy * dy) * scale
            tab[y * w + x] = int(d) & 0xFF
    return tab


try:
    @micropython.viper
    def _plasma_kernel(gray, w: int, h: int,
                       tx: int, ty: int, txy: int, tr: int,
                       sin_tab, radial_tab):
        """Interference plasma: sum of four sinusoidal terms per pixel.

        Each sin table entry is (sin(phase) * 127 + 128), stored as uint8.
        We subtract 128 to recover signed range -128..127, sum four terms
        (range -512..511), then rescale to 0..255 via (sum + 512) >> 2.
        """
        g  = ptr8(gray)
        st = ptr8(sin_tab)
        rt = ptr8(radial_tab)

        y: int = 0
        while y < h:
            # Row-constant y term
            sy: int = int(st[(y + ty) & 0xFF]) - 128
            row: int = y * w
            x: int = 0
            while x < w:
                sx:  int = int(st[(x + tx) & 0xFF]) - 128
                sxy: int = int(st[((x + y) + txy) & 0xFF]) - 128
                sr:  int = int(st[(int(rt[row + x]) + tr) & 0xFF]) - 128
                total: int = sx + sy + sxy + sr
                # total is in [-512, 511]; normalize to [0, 255]
                g[row + x] = ((total + 512) >> 2) & 0xFF
                x += 1
            y += 1

    @micropython.viper
    def _metaballs_kernel(gray, w: int, h: int,
                          centers, n_centers: int, strength: int):
        """Sum of inverse-square field from n_centers moving points.

        centers: bytearray of 2*n_centers bytes, [x0, y0, x1, y1, ...]
        strength: scaling factor applied per center (typically 48-128)

        Each pixel: sum over centers of strength * 256 / (1 + dx^2 + dy^2)
        Clamp to 255.
        """
        g = ptr8(gray)
        c = ptr8(centers)

        y: int = 0
        while y < h:
            row: int = y * w
            x: int = 0
            while x < w:
                acc: int = 0
                i: int = 0
                while i < n_centers:
                    cx: int = int(c[i * 2])
                    cy: int = int(c[i * 2 + 1])
                    dx: int = x - cx
                    dy: int = y - cy
                    d2: int = dx * dx + dy * dy + 1
                    acc += (strength * 256) // d2
                    i += 1
                if acc > 255:
                    acc = 255
                g[row + x] = acc & 0xFF
                x += 1
            y += 1

    @micropython.viper
    def _tunnel_kernel(gray, w: int, h: int, t: int,
                       angle_tab, dist_tab, sin_tab):
        """Tunnel effect: phase = angle + distance + t, sampled via sin_tab.

        angle_tab, dist_tab: precomputed w*h byte tables for each pixel's
        angular and radial coordinate (scaled to 0..255).
        """
        g  = ptr8(gray)
        at = ptr8(angle_tab)
        dt = ptr8(dist_tab)
        st = ptr8(sin_tab)

        y: int = 0
        while y < h:
            row: int = y * w
            x: int = 0
            while x < w:
                a: int = int(at[row + x])
                d: int = int(dt[row + x])
                phase: int = (a + d + t) & 0xFF
                g[row + x] = int(st[phase])
                x += 1
            y += 1

except Exception:
    def _plasma_kernel(gray, w, h, tx, ty, txy, tr, sin_tab, radial_tab):
        for y in range(h):
            sy = sin_tab[(y + ty) & 0xFF] - 128
            for x in range(w):
                sx  = sin_tab[(x + tx) & 0xFF] - 128
                sxy = sin_tab[((x + y) + txy) & 0xFF] - 128
                sr  = sin_tab[(radial_tab[y * w + x] + tr) & 0xFF] - 128
                total = sx + sy + sxy + sr
                gray[y * w + x] = ((total + 512) >> 2) & 0xFF

    def _metaballs_kernel(gray, w, h, centers, n_centers, strength):
        for y in range(h):
            for x in range(w):
                acc = 0
                for i in range(n_centers):
                    dx = x - centers[i * 2]
                    dy = y - centers[i * 2 + 1]
                    acc += (strength * 256) // (dx * dx + dy * dy + 1)
                gray[y * w + x] = min(255, acc) & 0xFF

    def _tunnel_kernel(gray, w, h, t, angle_tab, dist_tab, sin_tab):
        for y in range(h):
            for x in range(w):
                a = angle_tab[y * w + x]
                d = dist_tab[y * w + x]
                gray[y * w + x] = sin_tab[(a + d + t) & 0xFF]


# Shared sin table — all fields use the same one, so share it globally
# on import to save memory when multiple field objects are alive.
_SIN_TAB = None


def _get_sin_tab():
    global _SIN_TAB
    if _SIN_TAB is None:
        _SIN_TAB = _build_sin_tab_128()
    return _SIN_TAB


class Plasma:
    """Interference plasma: four sinusoidal terms summed per pixel.

    Each term has its own phase speed, so the overall pattern never
    quite repeats. The radial term keeps it from looking striped.

    Usage:
        p = Plasma(80, 80)
        gray = p.step()              # advance one frame
        draw_gray_rect(v, 40, 40, 80, 80, gray, mode="fs")
    """

    def __init__(self, w, h, speeds=(2, 3, 1, 5)):
        self.w = w
        self.h = h
        self.sin_tab = _get_sin_tab()
        self.radial_tab = _build_radial_tab(w, h)
        self.gray = bytearray(w * h)
        self.frame = 0
        # Phase increment per frame for each term: (x, y, x+y, radial)
        self.speeds = speeds

    def step(self):
        self.frame += 1
        f = self.frame
        sx, sy, sxy, sr = self.speeds
        _plasma_kernel(self.gray, self.w, self.h,
                       (f * sx) & 0xFF,
                       (f * sy) & 0xFF,
                       (f * sxy) & 0xFF,
                       (f * sr) & 0xFF,
                       self.sin_tab, self.radial_tab)
        return self.gray


class Metaballs:
    """Soft-bodied blob field: sum of inverse-square potential from N
    moving centers.

    Each center follows a lissajous path around the field; pass your
    own center positions via set_centers() for custom motion.

    Usage:
        m = Metaballs(80, 80, n=3)
        gray = m.step()
    """

    def __init__(self, w, h, n=3, strength=96):
        self.w = w
        self.h = h
        self.n = n
        self.strength = strength
        self.gray = bytearray(w * h)
        self.centers = bytearray(2 * n)
        self.frame = 0
        # Precompute per-ball lissajous parameters for default motion
        self._ax = [w // 3 for _ in range(n)]
        self._ay = [h // 3 for _ in range(n)]
        self._fx = [1 + i for i in range(n)]
        self._fy = [2 + i for i in range(n)]
        self._phase = [i * 40 for i in range(n)]

    def set_centers(self, positions):
        """Override center positions. positions is a list of (x, y)."""
        for i, (x, y) in enumerate(positions[:self.n]):
            self.centers[i * 2]     = int(x) & 0xFF
            self.centers[i * 2 + 1] = int(y) & 0xFF

    def step(self):
        self.frame += 1
        t = self.frame
        cx = self.w // 2
        cy = self.h // 2
        sin_tab = self.sin_tab if hasattr(self, "sin_tab") else _get_sin_tab()
        self.sin_tab = sin_tab
        # Move centers along lissajous paths using the shared sin table.
        # sin_tab values are 0..255 offset by 128; recover signed.
        for i in range(self.n):
            px = (t * self._fx[i] + self._phase[i]) & 0xFF
            py = (t * self._fy[i] + self._phase[i]) & 0xFF
            sx = sin_tab[px] - 128
            sy = sin_tab[py] - 128
            x = cx + (self._ax[i] * sx) // 128
            y = cy + (self._ay[i] * sy) // 128
            if x < 0: x = 0
            if x > 255: x = 255
            if y < 0: y = 0
            if y > 255: y = 255
            self.centers[i * 2]     = x
            self.centers[i * 2 + 1] = y
        _metaballs_kernel(self.gray, self.w, self.h,
                          self.centers, self.n, self.strength)
        return self.gray


class Tunnel:
    """Tunnel/vortex effect: phase advances with both angle and distance,
    sampled through the sin table.

    Precomputes angle and distance tables at construction, so step() is
    essentially one table lookup plus one sin lookup per pixel.
    """

    def __init__(self, w, h, speed=3):
        self.w = w
        self.h = h
        self.speed = speed
        self.sin_tab = _get_sin_tab()
        self.angle_tab = bytearray(w * h)
        self.dist_tab = bytearray(w * h)
        self.gray = bytearray(w * h)
        self.frame = 0

        cx = w / 2.0
        cy = h / 2.0
        # Scale distance so mid-field covers several sin periods
        for y in range(h):
            for x in range(w):
                dx = x - cx
                dy = y - cy
                # atan2 returns [-pi, pi], scale to 0..255
                a = math.atan2(dy, dx)
                self.angle_tab[y * w + x] = int((a + math.pi) * 40.6) & 0xFF
                # sqrt then scale; tweak the multiplier to taste
                d = math.sqrt(dx * dx + dy * dy)
                self.dist_tab[y * w + x] = int(d * 4) & 0xFF

    def step(self):
        self.frame += 1
        t = (self.frame * self.speed) & 0xFF
        _tunnel_kernel(self.gray, self.w, self.h, t,
                       self.angle_tab, self.dist_tab, self.sin_tab)
        return self.gray


# -----------------------------------------------------------------------
# Lissajous curve and trail field
# -----------------------------------------------------------------------
#
# A Lissajous curve is x(t) = A sin(a*t + dx), y(t) = B sin(b*t + dy).
# The ratio a:b controls the figure's shape: 1:1 gives a line/circle/
# ellipse depending on the phase difference; 2:3 gives the classic
# three-lobed figure; 5:7 gives a dense weave. The curve is closed and
# periodic when a/b is rational, taking gcd(a,b) "trips" to complete.
#
# We use the precomputed sin_tab from earlier in this module (same one
# all the field kernels share) so sampling a curve point is two table
# lookups and a couple of adds. No floating-point math in the hot path.


# Preset curve parameter sets. Each is (a, b, phase_x, phase_y). The
# phase difference between x and y is what distinguishes a circle (1:1
# with dx-dy = 64 = 90°) from a line (1:1 with dx-dy = 0). With a:b > 1
# the phase offset shifts the figure's orientation/symmetry.
LISSAJOUS_PRESETS = (
    # (a, b, dx, dy, name)
    (1, 1,  0, 64, "circle"),       # 1:1, 90deg phase = circle
    (1, 2,  0,  0, "figure-8"),     # 1:2 horizontal figure-eight
    (2, 3,  0,  0, "trefoil"),      # 2:3 three-lobed classic
    (3, 4,  0,  0, "4-lobe"),       # 3:4 four-lobed
    (3, 5,  0,  0, "rose-3-5"),     # 3:5 rose-like
    (5, 7,  0,  0, "weave"),        # 5:7 dense interleave
    (4, 5, 32,  0, "tilted"),       # 4:5 with offset
)


class Lissajous:
    """Parametric Lissajous curve sampler with hybrid morph/snap behavior.

    The curve parameters (a, b, phase offsets, amplitudes) are continuously
    perturbed by small per-frame drift, AND they snap to a new preset
    every `snap_period` frames. This gives the "constantly moving"
    character of mode 2 plus the "fresh new figure" rhythm of mode 3.

    Drift is small and slow — the figure visibly morphs but doesn't lose
    its identity between snaps. The snap is instantaneous so the new
    figure starts crisp.

    Sampling: call point(t) for integer t (frame counter). Returns
    (x, y) coordinates centered on the field; out-of-bounds is the
    caller's problem (TrailField clips when splatting).
    """

    def __init__(self, w, h, snap_period=240, sin_tab=None):
        self.w = w
        self.h = h
        self.cx = w // 2
        self.cy = h // 2
        # Amplitudes leave a small margin so the curve doesn't kiss edges
        self.ax_base = (w // 2) - 2
        self.ay_base = (h // 2) - 2
        self.sin_tab = sin_tab if sin_tab is not None else _get_sin_tab()

        self.snap_period = snap_period
        self.frames_since_snap = 0
        self.preset_idx = 0
        self._load_preset(0)

        # Drift state — these accumulate slowly between snaps
        self.drift_dx = 0    # phase drift, applied to dx
        self.drift_dy = 0    # phase drift, applied to dy
        self.amp_drift = 0   # amplitude pulsation phase

    def _load_preset(self, idx):
        a, b, dx, dy, name = LISSAJOUS_PRESETS[idx % len(LISSAJOUS_PRESETS)]
        self.a = a
        self.b = b
        self.dx = dx
        self.dy = dy
        self.name = name
        self.frames_since_snap = 0
        self.drift_dx = 0
        self.drift_dy = 0

    def snap_next(self):
        """Manually advance to the next preset. Called automatically on
        snap_period, but can be triggered externally too."""
        self.preset_idx = (self.preset_idx + 1) % len(LISSAJOUS_PRESETS)
        self._load_preset(self.preset_idx)

    def snap_prev(self):
        self.preset_idx = (self.preset_idx - 1) % len(LISSAJOUS_PRESETS)
        self._load_preset(self.preset_idx)

    def advance_drift(self):
        """Tick the slow morph. Call once per frame."""
        self.frames_since_snap += 1
        if self.frames_since_snap >= self.snap_period:
            self.snap_next()
            return

        # Slow phase drift. The drifts are in phase units (0..255 = 0..2pi).
        # ~1 unit every few frames means the figure visibly rotates/morphs
        # over the course of a few seconds without rushing.
        if (self.frames_since_snap & 3) == 0:
            self.drift_dx = (self.drift_dx + 1) & 0xFF
        if (self.frames_since_snap & 5) == 0:
            self.drift_dy = (self.drift_dy + 1) & 0xFF
        self.amp_drift = (self.amp_drift + 1) & 0xFF

    def point(self, t):
        """Sample the curve at integer parameter t.

        t is in phase units — 256 of them is one full sin period. The
        curve is closed and traversed every lcm(a, b) full sin periods.
        For typical caller usage, just pass a per-frame-incrementing
        counter and the curve traces continuously.
        """
        s = self.sin_tab
        # signed sin in -128..127 from table-with-+128-offset
        sx = s[(self.a * t + self.dx + self.drift_dx) & 0xFF] - 128
        sy = s[(self.b * t + self.dy + self.drift_dy) & 0xFF] - 128

        # Gentle amplitude pulse — ~6% in each axis, drifting slowly
        amp_mod = (s[self.amp_drift] - 128) >> 4   # roughly +/- 8 range
        ax = self.ax_base + amp_mod
        ay = self.ay_base - amp_mod

        # Final coordinates: scale -128..127 -> -ax..ax then center
        x = self.cx + ((ax * sx) >> 7)
        y = self.cy + ((ay * sy) >> 7)
        return x, y


class TrailField:
    """Stateful "comet trail" field. Each frame: decay the buffer,
    then stamp a new segment of the curve at full brightness.

    Exposes the standard field interface — `.step()` returns a grayscale
    bytearray ready for dithering. From the dither layer's perspective
    this is just another field producer, indistinguishable from Plasma.

    Parameters:
        curve:       any object with a .point(t) method returning (x, y)
                     and an optional .advance_drift() method.
                     Lissajous works directly; you can write your own.
        fade_frames: how many frames a pixel takes to fully decay from
                     full brightness. 240 = 4 seconds at 60 fps.
        fade_mode:   "linear" (comet, hard tail edge) or
                     "exp" (phosphor, smooth asymptote)
        steps_per_frame: how many curve samples to draw between this
                     frame and the last. Higher = smoother fast-moving
                     curves. 8-16 is typical.
        head_intensity: brightness of new pixels. 255 default; lower
                     gives a dimmer, more delicate trail.

    Internal state: the gray buffer is the trail map and persists across
    frames. It's also returned by step(), so don't hold references
    expecting it to be unchanged.
    """

    def __init__(self, w, h, curve,
                 fade_frames=240, fade_mode="linear",
                 steps_per_frame=12, head_intensity=255):
        self.w = w
        self.h = h
        self.curve = curve
        self.gray = bytearray(w * h)
        self.fade_mode = fade_mode
        self.steps_per_frame = steps_per_frame
        self.head_intensity = head_intensity

        # Convert "lifetime in frames" to per-frame decay parameter.
        # For linear: amount = head_intensity / fade_frames, so a pixel
        # written at head_intensity reaches 0 in fade_frames frames.
        # For exp: amount sized so 64% (~1/e) decay happens around
        # fade_frames * 0.6 — feels similar duration to linear in practice.
        if fade_mode == "linear":
            self.fade_amount = max(1, head_intensity // fade_frames)
        elif fade_mode == "exp":
            # mul = 256 - amount; want mul^fade_frames ~= 1 (negligible)
            # log_2(1/255) ≈ -8, so 8 / fade_frames bits per step.
            # Practical: amount = max(1, 2048 / fade_frames)
            self.fade_amount = max(1, 2048 // fade_frames)
        else:
            raise ValueError("fade_mode must be 'linear' or 'exp'")

        # Track last endpoint so we can connect successive frames with
        # lines, not gaps. Initialize at curve start.
        self.t = 0
        self.last_x, self.last_y = curve.point(0)

    def step(self):
        # 1. Fade the whole buffer
        _effects.fade(self.gray, self.w, self.h,
                      amount=self.fade_amount, mode=self.fade_mode)

        # 2. Stamp the new curve segment. Sample steps_per_frame points
        # between the last endpoint and the new one, connecting each
        # consecutive pair with a Bresenham line.
        steps = self.steps_per_frame
        # Sub-frame phase units: divide one frame's worth of "t advance"
        # into `steps` sub-steps. We advance t by 1 unit per frame here,
        # which means the curve takes 256 frames per full period — slow
        # enough that motion is graceful, fast enough that you see it.
        for i in range(1, steps + 1):
            sub_t = self.t + (i / steps)
            # Convert to integer phase units. Multiply by some scale to
            # make the curve move at a visually interesting speed.
            phase = int(sub_t * 4) & 0xFFFF
            x, y = self.curve.point(phase)
            _effects.splat_line(self.gray, self.w, self.h,
                                self.last_x, self.last_y, x, y,
                                intensity=self.head_intensity)
            self.last_x, self.last_y = x, y

        self.t += 1
        # 3. Advance the curve's slow morph state
        if hasattr(self.curve, "advance_drift"):
            self.curve.advance_drift()

        return self.gray


# Lazy import to keep effects.py optional. Anyone using only Plasma/
# Metaballs/Tunnel doesn't need it loaded.
try:
    import effects as _effects
except ImportError:
    _effects = None
