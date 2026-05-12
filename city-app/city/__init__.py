"""
City demo - milestone 1: camera spline + reference cube at origin.

What you should see:
  - A shaded cube (filled triangles, face-light dither) at world origin.
  - The camera orbiting it in a slow ring, with altitude rising and
    falling on a smooth low->high->low cycle.
  - Speed visibly modulated: slow when low (~15 u/s), faster when high
    (~50 u/s).
  - The cube stays roughly centered in view at all times.

If the cube jitters or pops at waypoint boundaries, the spline math is
wrong. If the cube drifts off-screen, the look-at is wrong. If the
camera lurches when crossing waypoints, the speed parameterization or
chord-length advance is wrong.

Subsequent milestones will replace the reference cube with the
chunk-based city.
"""

import esclib as elib
import pdeck
import time
import array
import dsplib as dl
import math

from city.camera import Camera


# Reference cube, scaled up so it's clearly visible from camera distance ~180.
_CUBE_SCALE = 12.0

_V_RAW = [
  [-1,-1,-1], [ 1,-1,-1], [ 1, 1,-1], [-1, 1,-1],
  [-1,-1, 1], [ 1,-1, 1], [ 1, 1, 1], [-1, 1, 1],
]
_NUV = len(_V_RAW)
_VERTS = array.array('f', [0.0] * (_NUV * 3))
for i, v in enumerate(_V_RAW):
  _VERTS[i*3 + 0] = v[0] * _CUBE_SCALE
  _VERTS[i*3 + 1] = v[1] * _CUBE_SCALE
  _VERTS[i*3 + 2] = v[2] * _CUBE_SCALE

_F_RAW = [
  (0,1,2), (2,3,0),  # front
  (1,5,6), (6,2,1),  # right
  (7,6,5), (5,4,7),  # back
  (4,0,3), (3,7,4),  # left
  (4,5,1), (1,0,4),  # bottom
  (3,2,6), (6,7,3),  # top
]
_NF = len(_F_RAW)
_IDX = array.array('H', [0] * (_NF * 3))
for i, f in enumerate(_F_RAW):
  _IDX[i*3 + 0] = f[0]
  _IDX[i*3 + 1] = f[1]
  _IDX[i*3 + 2] = f[2]

# Face normals: winding gives an inward cross product, so we negate.
_NORMS = array.array('f', [0.0] * (_NF * 3))
for i, f in enumerate(_F_RAW):
  p0, p1, p2 = _V_RAW[f[0]], _V_RAW[f[1]], _V_RAW[f[2]]
  u = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
  w = (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2])
  nx = u[1]*w[2] - u[2]*w[1]
  ny = u[2]*w[0] - u[0]*w[2]
  nz = u[0]*w[1] - u[1]*w[0]
  nl = math.sqrt(nx*nx + ny*ny + nz*nz)
  _NORMS[i*3 + 0] = -nx/nl
  _NORMS[i*3 + 1] = -ny/nl
  _NORMS[i*3 + 2] = -nz/nl

# Projection params. Wider FOV than cube_test for more cinematic feel
# (the cube_test value of 120 is nearly fisheye; 200 gives ~90 deg
# horizontal which reads better for city flyovers).
_FOV = 200.0
_CX = 200.0
_CY = 120.0


class CityDemo:

  def __init__(self, vscreen):
    self.v = vscreen
    self.last_us = time.ticks_us()
    self.camera = Camera()

    self.matrix = array.array('f', [0.0] * 16)
    self.light = array.array('f', [0.5, 0.7, -1.0])
    self.out_poly = array.array('h', [0] * (_NF * 6))
    self.out_dither = array.array('b', [0] * _NF)
    self.depths = array.array('i', [0] * _NF)
    self.sort_idx = array.array('H', range(_NF))
    self.temp_verts = array.array('f', [0.0] * (_NUV * 3))
    self.temp_norms = array.array('f', [0.0] * (_NF * 3))
    self.mv_poly = memoryview(self.out_poly)

    self._fps_ema = 30.0

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return

    now = time.ticks_us()
    diff = time.ticks_diff(now, self.last_us)
    self.last_us = now
    dt = diff / 1000000.0
    if dt > 0.1:
      dt = 0.1

    inst_fps = 1.0/dt if dt > 0 else 0.0
    self._fps_ema = 0.92*self._fps_ema + 0.08*inst_fps

    # Camera advances, then we build the view matrix used for every
    # piece of world geometry this frame. In milestone 1 that's just
    # the reference cube; from milestone 2 it'll be every chunk mesh.
    self.camera.update(dt)
    self.camera.view_matrix(self.matrix)

    dl.project_3d_indexed(
      self.matrix, _VERTS, _IDX, _NORMS, self.light,
      _NF, _NUV,
      _FOV, _CX, _CY,
      self.out_poly, self.out_dither, self.depths,
      self.temp_verts, self.temp_norms,
    )
    dl.sort_indices(self.sort_idx, self.depths, 0)

    self.v.set_draw_color(1)
    for i in self.sort_idx:
      d = self.out_dither[i]
      if d >= 0:
        self.v.set_dither(d)
        self.v.draw_polygon(self.mv_poly[i*6 : i*6 + 6])

    # HUD
    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(5, 12, "CITY M1 SPLINE  {:.0f} FPS".format(self._fps_ema))
    self.v.draw_str(5, 24, "POS  X{:6.0f}  Y{:5.0f}  Z{:6.0f}".format(
      self.camera.pos[0], self.camera.pos[1], self.camera.pos[2]))
    self.v.draw_str(5, 36, "SPD  {:5.1f} u/s".format(self.camera.speed))
    self.v.draw_str(5, 48, "Q to exit")

    self.v.finished()


def main(vs, args):
  el = elib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  demo = CityDemo(v)
  v.callback(demo.update)
  vs.read(1)
  v.callback(None)
  v.print(el.display_mode(True))
  print("finished.", file=vs)
