"""
City demo - milestone 3 v2: near-plane + screen-coord cull.

Adds a second guard on top of the near-plane cull: any face whose
projected screen coords fall outside +/- _MAX_SCREEN_COORD is culled.
This catches the case where a vertex has positive tz (passing the
near-plane test) but small enough that the perspective extrapolation
produces a polygon spanning thousands of pixels.

Press F5 to reload, then move with the camera for a few seconds; the
first frame after reload dumps culling statistics to the terminal so
we can confirm the guards are biting the intended cases.
"""

import esclib as elib
import pdeck
import time
import array
import dsplib as dl

from city.camera import Camera
from city.chunks import ChunkGrid, CHUNK_SIZE


# Projection params
_FOV = 200.0
_CX = 200.0
_CY = 120.0

# Depth fog, units of 1024 per dsplib depth scale.
_FOG_NEAR_M = 30.0
_FOG_FAR_M  = 200.0
_FOG_NEAR_D = int(_FOG_NEAR_M * 1024)
_FOG_FAR_D  = int(_FOG_FAR_M  * 1024)
_FOG_RANGE  = _FOG_FAR_D - _FOG_NEAR_D

# Camera-space near plane. Bumped from 2m to 10m: gives perspective
# extrapolation enough headroom that lateral coords don't explode.
_NEAR_PLANE = 10.0

# Max allowable absolute screen coordinate after projection. Anything
# beyond is treated as a near-plane extrapolation artifact and culled.
# 2000 = 5x screen width, plenty of slack for legitimate large off-screen
# polygons while still catching the catastrophic ones.
_MAX_SCREEN_COORD = 2000


class CityDemo:

  def __init__(self, vscreen):
    self.v = vscreen
    self.last_us = time.ticks_us()
    self.camera = Camera()
    self.grid = ChunkGrid()
    self.matrix = array.array('f', [0.0] * 16)
    self.light = array.array('f', [0.5, 0.7, -1.0])

    self._fps_ema = 30.0
    self._visible_chunks = 0
    self._visible_faces = 0
    self._visible_list = []

    # Cull diagnostics. Dumped once after _DIAG_DELAY seconds so the
    # camera has time to be in interesting position before snapshot.
    self._diag_dumped = False
    self._diag_t = 0.0
    self._diag_delay = 2.0

  def _post_pass(self, ch, diag):
    """Near-plane cull, screen-coord cull, then depth fog. One loop."""
    indices    = ch.indices
    temp_verts = ch.temp_verts
    depths     = ch.depths
    dither     = ch.out_dither
    out_poly   = ch.out_poly
    n_faces    = ch.n_faces

    near_d   = _FOG_NEAR_D
    far_d    = _FOG_FAR_D
    fog_rng  = _FOG_RANGE
    near_pl  = _NEAR_PLANE
    max_sc   = _MAX_SCREEN_COORD
    neg_sc   = -max_sc

    near_culled = 0
    screen_culled = 0
    fog_culled = 0
    drawn = 0

    for i in range(n_faces):
      d = dither[i]
      if d < 0:
        continue

      # Guard 1: near-plane cull on camera-space Z.
      base3 = i * 3
      v0 = indices[base3]
      v1 = indices[base3 + 1]
      v2 = indices[base3 + 2]
      if (temp_verts[v0 * 3 + 2] < near_pl or
          temp_verts[v1 * 3 + 2] < near_pl or
          temp_verts[v2 * 3 + 2] < near_pl):
        dither[i] = -1
        near_culled += 1
        continue

      # Guard 2: screen-coord sanity. Cull faces with projected coords
      # implying perspective extrapolation gone wild.
      base6 = i * 6
      bad = False
      for j in range(6):
        c = out_poly[base6 + j]
        if c > max_sc or c < neg_sc:
          bad = True
          break
      if bad:
        dither[i] = -1
        screen_culled += 1
        continue

      # Depth fog.
      z = depths[i]
      if z >= far_d:
        dither[i] = -1
        fog_culled += 1
        continue
      if z > near_d:
        t = (z - near_d) / fog_rng
        scale = 1.0 - t * t
        new_d = int(d * scale)
        if new_d <= 0:
          dither[i] = -1
          fog_culled += 1
          continue
        else:
          dither[i] = new_d

      drawn += 1

    if diag is not None:
      diag[0] += near_culled
      diag[1] += screen_culled
      diag[2] += fog_culled
      diag[3] += drawn

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

    self.camera.update(dt)
    self.camera.view_matrix(self.matrix)
    self.grid.update(self.camera.pos[0], self.camera.pos[2])

    cam_x = self.camera.pos[0]
    cam_z = self.camera.pos[2]
    fwd_x = self.camera.forward[0]
    fwd_z = self.camera.forward[2]

    # Track diagnostics for one frame after _diag_delay seconds.
    self._diag_t += dt
    take_diag = (not self._diag_dumped and self._diag_t >= self._diag_delay)
    diag = [0, 0, 0, 0] if take_diag else None  # near, screen, fog, drawn

    self._visible_list.clear()
    cull_dot = -CHUNK_SIZE * 0.5
    for ch in self.grid.chunks.values():
      dx = ch.cx_world - cam_x
      dz = ch.cz_world - cam_z
      if dx * fwd_x + dz * fwd_z <= cull_dot:
        continue
      self._visible_list.append((dx*dx + dz*dz, ch))
    self._visible_list.sort(key=lambda p: -p[0])

    vc = 0
    vf = 0
    self.v.set_draw_color(1)
    for _, ch in self._visible_list:
      dl.project_3d_indexed(
        self.matrix, ch.verts, ch.indices, ch.normals, self.light,
        ch.n_faces, ch.n_verts,
        _FOV, _CX, _CY,
        ch.out_poly, ch.out_dither, ch.depths,
        ch.temp_verts, ch.temp_norms,
      )
      self._post_pass(ch, diag)
      dl.sort_indices(ch.sort_idx, ch.depths, 0)

      out_poly = ch.out_poly
      out_dither = ch.out_dither
      mv = memoryview(out_poly)
      n = ch.n_faces
      for k in range(n):
        i = ch.sort_idx[k]
        d = out_dither[i]
        if d >= 0:
          self.v.set_dither(d)
          self.v.draw_polygon(mv[i*6 : i*6 + 6])
          vf += 1

      vc += 1
    self._visible_chunks = vc
    self._visible_faces = vf

    if take_diag:
      import sys
      print("CULL DIAG: near={}  screen={}  fog={}  drawn={}".format(
        diag[0], diag[1], diag[2], diag[3]), file=sys.stderr)
      print("  cam pos=({:.1f}, {:.1f}, {:.1f})  fwd=({:.2f},{:.2f})".format(
        cam_x, self.camera.pos[1], cam_z, fwd_x, fwd_z), file=sys.stderr)
      self._diag_dumped = True

    # HUD
    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(5, 12, "CITY M3v2  {:.0f} FPS".format(self._fps_ema))
    self.v.draw_str(5, 24, "POS X{:5.0f} Y{:4.0f} Z{:5.0f}".format(
      cam_x, self.camera.pos[1], cam_z))
    self.v.draw_str(5, 36, "SPD {:4.1f} u/s".format(self.camera.speed))
    self.v.draw_str(5, 48, "CHUNKS {} VIS {} TOT  FACES {}".format(
      self._visible_chunks, len(self.grid.chunks), self._visible_faces))
    self.v.draw_str(5, 60, "Q to exit")

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
