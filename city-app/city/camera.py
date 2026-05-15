"""
Camera with Catmull-Rom spline path and tangent-tracking look-at.

The camera moves through the city along a smooth forward path:
  - Net travel along +X (the "boulevard direction")
  - Sinusoidal Z weave so the camera meanders between building columns
  - Altitude rising/falling on a smooth low->high->low cycle
  - Speed modulated by altitude (slow when low, fast when high)
  - Look-at target on a second spline running ahead of the camera,
    biased slightly downward so the city stays in frame

Waypoints are generated lazily as the camera advances, so the path is
effectively infinite. Travel is parameterized by chord length so
self.speed maps directly to world units per second.
"""

import math


def _catmull_rom(p0, p1, p2, p3, t):
  """Uniform Catmull-Rom interpolation between p1 and p2.

  See milestone 1 notes for the basis-function derivation. Curve passes
  through p1 (t=0) and p2 (t=1), C1-continuous at every waypoint.
  """
  t2 = t * t
  t3 = t2 * t
  b0 = -0.5*t3 + t2 - 0.5*t
  b1 =  1.5*t3 - 2.5*t2 + 1.0
  b2 = -1.5*t3 + 2.0*t2 + 0.5*t
  b3 =  0.5*t3 - 0.5*t2
  return (
    b0*p0[0] + b1*p1[0] + b2*p2[0] + b3*p3[0],
    b0*p0[1] + b1*p1[1] + b2*p2[1] + b3*p3[1],
    b0*p0[2] + b1*p1[2] + b2*p2[2] + b3*p3[2],
  )


def _chord_len(a, b):
  dx, dy, dz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
  return math.sqrt(dx*dx + dy*dy + dz*dz)


class Camera:
  """Spline-driven forward-flight camera.

  Call update(dt) each frame, then view_matrix(out) to write the 4x4
  world->camera transform.
  """

  # Path geometry (world units = meters)
  STEP_X = 80.0        # waypoint-to-waypoint advance along +X
  WEAVE_AMP = 35.0     # sinusoidal Z weave amplitude
  WEAVE_PERIOD = 4     # waypoints per full sine cycle of weave

  # Altitude band
  ALT_LOW = 14.0
  ALT_HIGH = 130.0
  ALT_PERIOD = 8       # waypoints per altitude cycle (longer than weave)

  # Speed (world units per second), modulated by altitude
  SPEED_LOW = 18.0
  SPEED_HIGH = 55.0

  # Look-at target lookahead distance along the path
  LOOKAHEAD = 1.5      # in waypoints
  TARGET_DOWN_BIAS = 12.0  # target dropped by this much in world Y

  def __init__(self):
    self.pos = [0.0, 0.0, 0.0]
    self.target = [0.0, 0.0, 0.0]
    self.forward = [0.0, 0.0, 1.0]  # for chunk-grid visibility culling
    self.speed = self.SPEED_LOW

    # Rolling 4-waypoint window for the position spline.
    # Active segment runs _wp[1] -> _wp[2]; _wp[0] / _wp[3] anchor tangents.
    self._wp = []
    self._wp_idx = 0
    for i in range(4):
      self._wp.append(self._gen_waypoint(i))
      self._wp_idx += 1

    self._seg_dist = 0.0
    self._seg_len = _chord_len(self._wp[1], self._wp[2])

    # Prime first frame so pos/target/forward are valid before render.
    self.update(0.0)

  def _gen_waypoint(self, idx):
    """Deterministic waypoint along the city flight path."""
    x = idx * self.STEP_X
    # Weave on a sine
    z = self.WEAVE_AMP * math.sin(idx * (2.0 * math.pi / self.WEAVE_PERIOD))
    # Altitude on a smooth (0..1) cosine cycle
    phase = (idx % self.ALT_PERIOD) * (2.0 * math.pi / self.ALT_PERIOD)
    mix = 0.5 - 0.5 * math.cos(phase)
    y = self.ALT_LOW + (self.ALT_HIGH - self.ALT_LOW) * mix
    return (x, y, z)

  def _target_at(self, wp_progress):
    """Compute the look-at target at fractional waypoint index wp_progress.

    Samples the path LOOKAHEAD waypoints ahead and drops Y by the
    downward bias. Uses the same Catmull-Rom window logic as the
    position spline, advancing by LOOKAHEAD into the future. To avoid
    rebuilding a parallel waypoint stream, we just call _gen_waypoint
    at integer offsets around the look point.
    """
    look = wp_progress + self.LOOKAHEAD
    base = int(math.floor(look))
    t = look - base
    p0 = self._gen_waypoint(base - 1)
    p1 = self._gen_waypoint(base)
    p2 = self._gen_waypoint(base + 1)
    p3 = self._gen_waypoint(base + 2)
    x, y, z = _catmull_rom(p0, p1, p2, p3, t)
    return (x, y - self.TARGET_DOWN_BIAS, z)

  def _update_speed(self):
    alt = self.pos[1]
    band = (alt - self.ALT_LOW) / (self.ALT_HIGH - self.ALT_LOW)
    if band < 0.0: band = 0.0
    elif band > 1.0: band = 1.0
    self.speed = self.SPEED_LOW + (self.SPEED_HIGH - self.SPEED_LOW) * band

  def update(self, dt):
    if dt > 0.1:
      dt = 0.1

    self._update_speed()
    self._seg_dist += self.speed * dt

    # Advance segments. Safety bound prevents infinite loop on degenerate
    # segments (which shouldn't happen with this path but guards future me).
    safety = 0
    while (self._seg_dist >= self._seg_len and
           self._seg_len > 1e-3 and safety < 16):
      self._seg_dist -= self._seg_len
      self._wp.pop(0)
      self._wp.append(self._gen_waypoint(self._wp_idx))
      self._wp_idx += 1
      self._seg_len = _chord_len(self._wp[1], self._wp[2])
      safety += 1

    t = self._seg_dist / self._seg_len if self._seg_len > 1e-3 else 0.0
    x, y, z = _catmull_rom(self._wp[0], self._wp[1],
                           self._wp[2], self._wp[3], t)
    self.pos[0] = x
    self.pos[1] = y
    self.pos[2] = z

    # Look-at target: lookahead along the same path, biased down.
    # The "current waypoint progress" is (idx of _wp[1]) + t. We
    # tracked _wp_idx as one past the last appended, so _wp[1] sits at
    # _wp_idx - 3 in absolute waypoint indexing.
    wp_progress = (self._wp_idx - 3) + t
    tx, ty, tz = self._target_at(wp_progress)
    self.target[0] = tx
    self.target[1] = ty
    self.target[2] = tz

    # Forward vector for chunk-grid culling.
    fx = tx - x; fy = ty - y; fz = tz - z
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    if flen > 1e-6:
      inv = 1.0 / flen
      # Only XZ components used for culling
      self.forward[0] = fx * inv
      self.forward[1] = fy * inv
      self.forward[2] = fz * inv

  def view_matrix(self, out):
    """Write row-major 4x4 world->camera matrix into `out` (16 floats).

    Camera convention matches project_3d_indexed: +Z forward, +X right,
    +Y up. The matrix transforms world-space points into camera space
    such that points the camera looks at have positive Z.
    """
    ex = self.pos[0]; ey = self.pos[1]; ez = self.pos[2]
    tx = self.target[0]; ty = self.target[1]; tz = self.target[2]

    # forward = normalize(target - eye)
    fx = tx - ex; fy = ty - ey; fz = tz - ez
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    if flen < 1e-6:
      fx = 0.0; fy = 0.0; fz = 1.0
    else:
      inv = 1.0 / flen
      fx *= inv; fy *= inv; fz *= inv

    # right = normalize(cross(world_up, forward))
    # cross((0,1,0), (fx,fy,fz)) = (fz, 0, -fx)
    rx = fz; ry = 0.0; rz = -fx
    rlen = math.sqrt(rx*rx + rz*rz)
    if rlen < 1e-6:
      rx = 1.0; ry = 0.0; rz = 0.0
    else:
      inv = 1.0 / rlen
      rx *= inv; rz *= inv

    # up = cross(forward, right)
    ux = fy*rz - fz*ry
    uy = fz*rx - fx*rz
    uz = fx*ry - fy*rx

    out[0]  = rx;  out[1]  = ry;  out[2]  = rz
    out[3]  = -(rx*ex + ry*ey + rz*ez)
    out[4]  = ux;  out[5]  = uy;  out[6]  = uz
    out[7]  = -(ux*ex + uy*ey + uz*ez)
    out[8]  = fx;  out[9]  = fy;  out[10] = fz
    out[11] = -(fx*ex + fy*ey + fz*ez)
    out[12] = 0.0; out[13] = 0.0; out[14] = 0.0; out[15] = 1.0
