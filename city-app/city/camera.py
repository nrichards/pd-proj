"""
Camera with Catmull-Rom spline path and look-at view matrix.

The camera moves along a waypoint path interpolated as a uniform
Catmull-Rom spline. Waypoints are generated lazily as the camera
advances, so the path is effectively infinite. Travel is parameterized
by chord length (so the camera's actual world-space speed matches
self.speed, not a per-segment parametric rate), and speed is
altitude-modulated: slower when low (weaving), faster when high
(sweeping).

For milestone 1, look-at target is always world origin so the
reference cube stays centered. A separate look-at spline will be
introduced in milestone 2 when there's a real world to look at.
"""

import math


def _catmull_rom(p0, p1, p2, p3, t):
  """Uniform Catmull-Rom interpolation between p1 and p2.

  Returns (x, y, z) at parameter t in [0, 1]. p0..p3 are 3-tuples.
  The curve passes through p1 (at t=0) and p2 (at t=1), with tangents
  derived from p0->p2 and p1->p3; this makes the path C1-continuous
  at every waypoint.

  Expanded into basis functions per point:
    P(t) = b0*p0 + b1*p1 + b2*p2 + b3*p3
    b0 = -0.5 t^3 + t^2 - 0.5 t
    b1 =  1.5 t^3 - 2.5 t^2 + 1
    b2 = -1.5 t^3 + 2 t^2 + 0.5 t
    b3 =  0.5 t^3 - 0.5 t^2
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
  """Spline-driven camera. Call update(dt) each frame, then view_matrix(out)."""

  # Camera path: orbital radius and altitude band
  RADIUS = 180.0
  ALT_LOW = 12.0
  ALT_HIGH = 120.0
  ANG_PER_WP = 0.40   # XZ orbit advance per waypoint, radians
  ALT_PERIOD = 6      # waypoints per low->high->low altitude cycle

  # Speed (world units per second), modulated by altitude
  SPEED_LOW = 15.0
  SPEED_HIGH = 50.0

  def __init__(self):
    self.pos = [0.0, 0.0, 0.0]
    self.target = [0.0, 0.0, 0.0]
    self.speed = self.SPEED_LOW

    # Rolling 4-waypoint window. The active segment runs _wp[1] -> _wp[2];
    # _wp[0] and _wp[3] are the tangent anchors required by Catmull-Rom.
    self._wp = []
    self._wp_idx = 0
    for i in range(4):
      self._wp.append(self._gen_waypoint(i))
      self._wp_idx += 1

    self._seg_dist = 0.0  # how far along the current segment we've traveled
    self._seg_len = _chord_len(self._wp[1], self._wp[2])

    # Prime pos/target for first frame
    self.update(0.0)

  def _gen_waypoint(self, idx):
    """Deterministic waypoint generation. Replace this in milestone 2+
    when waypoints need to avoid buildings."""
    angle = idx * self.ANG_PER_WP
    # Altitude on a smooth low->high->low cosine cycle.
    phase = (idx % self.ALT_PERIOD) * (2.0 * math.pi / self.ALT_PERIOD)
    mix = 0.5 - 0.5 * math.cos(phase)  # 0..1, smooth
    y = self.ALT_LOW + (self.ALT_HIGH - self.ALT_LOW) * mix
    x = self.RADIUS * math.cos(angle)
    z = self.RADIUS * math.sin(angle)
    return (x, y, z)

  def _update_speed(self):
    """Update self.speed based on current altitude band."""
    alt = self.pos[1]
    band = (alt - self.ALT_LOW) / (self.ALT_HIGH - self.ALT_LOW)
    if band < 0.0: band = 0.0
    elif band > 1.0: band = 1.0
    self.speed = self.SPEED_LOW + (self.SPEED_HIGH - self.SPEED_LOW) * band

  def update(self, dt):
    if dt > 0.1:
      dt = 0.1  # clamp big stalls; lose motion rather than lurch

    self._update_speed()
    self._seg_dist += self.speed * dt

    # Advance to next segment as needed. Guard against degenerate
    # (near-zero-length) segments to avoid an infinite loop.
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

    # Milestone 1: always look at origin (the reference cube).
    self.target[0] = 0.0
    self.target[1] = 0.0
    self.target[2] = 0.0

  def view_matrix(self, out):
    """Write the row-major 4x4 world->camera view matrix into `out`
    (a 16-element float array).

    Camera convention matches project_3d_indexed: +Z forward, +X right,
    +Y up (left-handed). World up is +Y. The matrix transforms world-
    space points into camera space such that points the camera looks at
    end up at positive Z.
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
    rlen = math.sqrt(rx*rx + rz*rz)  # ry is always 0 here
    if rlen < 1e-6:
      # Camera looking straight up or down; pick a stable right.
      rx = 1.0; ry = 0.0; rz = 0.0
    else:
      inv = 1.0 / rlen
      rx *= inv; rz *= inv

    # up = cross(forward, right)
    ux = fy*rz - fz*ry
    uy = fz*rx - fx*rz
    uz = fx*ry - fy*rx

    # Row-major view matrix (world->camera).
    # Rows are the camera basis vectors expressed in world space, with
    # the translation column = -(basis . eye).
    out[0]  = rx;  out[1]  = ry;  out[2]  = rz
    out[3]  = -(rx*ex + ry*ey + rz*ez)
    out[4]  = ux;  out[5]  = uy;  out[6]  = uz
    out[7]  = -(ux*ex + uy*ey + uz*ez)
    out[8]  = fx;  out[9]  = fy;  out[10] = fz
    out[11] = -(fx*ex + fy*ey + fz*ez)
    out[12] = 0.0; out[13] = 0.0; out[14] = 0.0; out[15] = 1.0
