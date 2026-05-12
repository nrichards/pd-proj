"""
Stress test: render N cubes, sweep N over time, report FPS per level.

Use this to calibrate how many faces you can afford per frame on the
deck (and the desktop shim, for comparison). The sweep produces a table
at exit:

  Stress results:
    N=  1   12 faces   FPS=58.3
    N=  4   48 faces   FPS=42.1
    ...

City milestone 2+ will use per-chunk projection calls of ~30-50 faces
each, with ~20 visible chunks per frame. This stress matches that
pattern: N separate projection calls of 12 faces each (a cube).

Press any key to exit. After exit, the level table prints to terminal.
"""

import esclib as elib
import pdeck
import time
import array
import dsplib as dl
import math


# Cube geometry, same shape as cube_test
_V_RAW = [
  [-1,-1,-1], [ 1,-1,-1], [ 1, 1,-1], [-1, 1,-1],
  [-1,-1, 1], [ 1,-1, 1], [ 1, 1, 1], [-1, 1, 1],
]
_NUV = len(_V_RAW)
_VERTS = array.array('f', [0.0] * (_NUV * 3))
for i, v in enumerate(_V_RAW):
  _VERTS[i*3:i*3+3] = array.array('f', v)

_F_RAW = [
  (0,1,2),(2,3,0),(1,5,6),(6,2,1),
  (7,6,5),(5,4,7),(4,0,3),(3,7,4),
  (4,5,1),(1,0,4),(3,2,6),(6,7,3),
]
_NF = len(_F_RAW)
_IDX = array.array('H', [0] * (_NF * 3))
for i, f in enumerate(_F_RAW):
  _IDX[i*3:i*3+3] = array.array('H', f)

_NORMS = array.array('f', [0.0] * (_NF * 3))
for i, f in enumerate(_F_RAW):
  p0, p1, p2 = _V_RAW[f[0]], _V_RAW[f[1]], _V_RAW[f[2]]
  u = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
  w = (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2])
  nx = u[1]*w[2] - u[2]*w[1]
  ny = u[2]*w[0] - u[0]*w[2]
  nz = u[0]*w[1] - u[1]*w[0]
  nl = math.sqrt(nx*nx + ny*ny + nz*nz)
  _NORMS[i*3:i*3+3] = array.array('f', [-nx/nl, -ny/nl, -nz/nl])


_LEVELS = [1, 4, 9, 16, 25, 36, 49, 64, 81, 100]
_LEVEL_TIME = 3.0  # seconds per level


class Stress:

  def __init__(self, vs):
    self.v = vs
    self.last_us = time.ticks_us()
    self.t = 0.0
    self.angle = 0.0
    self.level_idx = 0
    self.level_t = 0.0
    self.frames_this_level = 0
    self.done = False
    self.results = []  # list of (n_cubes, avg_fps)

    self.matrix = array.array('f', [0.0] * 16)
    self.light = array.array('f', [0.5, 0.7, -1.0])
    self.rot = array.array('f', [0.0, 0.0, 0.0])
    self.pos = array.array('f', [0.0, 0.0, 0.0])
    self.scale = array.array('f', [6.0, 6.0, 6.0])

    self.out_poly = array.array('h', [0] * (_NF * 6))
    self.out_dither = array.array('b', [0] * _NF)
    self.depths = array.array('i', [0] * _NF)
    self.sort_idx = array.array('H', range(_NF))
    self.tv = array.array('f', [0.0] * (_NUV * 3))
    self.tn = array.array('f', [0.0] * (_NF * 3))
    self.mv = memoryview(self.out_poly)

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

    self.t += dt
    self.angle += dt * 0.3

    if not self.done:
      self.level_t += dt
      self.frames_this_level += 1
      if self.level_t >= _LEVEL_TIME and self.level_idx < len(_LEVELS):
        avg = self.frames_this_level / self.level_t
        self.results.append((_LEVELS[self.level_idx], avg))
        self.level_idx += 1
        self.level_t = 0.0
        self.frames_this_level = 0
        if self.level_idx >= len(_LEVELS):
          self.done = True

    n = _LEVELS[min(self.level_idx, len(_LEVELS) - 1)]
    grid = int(math.ceil(math.sqrt(n)))
    spacing = 22.0
    offset = -spacing * (grid - 1) * 0.5

    # Render N cubes, each with its own model matrix (rotation + position).
    # This exercises both set_transform_matrix_4x4 and project_3d_indexed.
    for c in range(n):
      row = c // grid
      col = c % grid
      self.pos[0] = offset + col * spacing
      self.pos[1] = offset + row * spacing
      self.pos[2] = 200.0
      self.rot[0] = self.angle + c * 0.1
      self.rot[1] = self.angle * 1.3

      dl.set_transform_matrix_4x4(self.matrix, self.rot, self.pos, self.scale)
      dl.project_3d_indexed(
        self.matrix, _VERTS, _IDX, _NORMS, self.light,
        _NF, _NUV,
        120.0, 200.0, 120.0,
        self.out_poly, self.out_dither, self.depths,
        self.tv, self.tn,
      )
      dl.sort_indices(self.sort_idx, self.depths, 0)
      for i in self.sort_idx:
        d = self.out_dither[i]
        if d >= 0:
          self.v.set_dither(d)
          self.v.draw_polygon(self.mv[i*6 : i*6 + 6])

    # HUD
    inst_fps = 1.0/dt if dt > 0 else 0.0
    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(5, 12, "STRESS  N={}  ({} faces)  {:.1f} FPS".format(
      n, n * _NF, inst_fps))
    if self.done:
      self.v.draw_str(5, 24, "DONE - press Q to exit & print table")
    else:
      self.v.draw_str(5, 24, "LEVEL {}/{}  {:.1f}/{:.1f}s".format(
        self.level_idx + 1, len(_LEVELS),
        self.level_t, _LEVEL_TIME))

    self.v.finished()


def main(vs, args):
  el = elib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  demo = Stress(v)
  v.callback(demo.update)
  vs.read(1)
  v.callback(None)
  v.print(el.display_mode(True))

  print("Stress results:", file=vs)
  for n, fps in demo.results:
    print("  N={:3d}  {:4d} faces  FPS={:5.1f}".format(
      n, n * _NF, fps), file=vs)
  print("finished.", file=vs)
