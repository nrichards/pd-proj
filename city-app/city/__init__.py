"""
City demo - milestone 3 final.

Building variety (regular / slab / stepped) + depth fog + chunk-sort
+ viper-accelerated post-pass with screen-coord guard + area cull.

Performance on device: ~17-25 fps depending on view density and
altitude. Fillrate (u8g2 polygon fill) is the dominant cost; geometry
pipeline runs in ~9-14 ms/frame combined.

Known visual issue: at certain camera/light/face combinations,
faces can disappear instead of rendering at low-density dither. The
dither=0 -> 1 clamp in _post_pass mitigates some cases but not all;
the residual is acceptable for now.
"""

import esclib as elib
import pdeck
import time
import array
import sys
import dsplib as dl

from city.camera import Camera
from city.chunks import ChunkGrid, CHUNK_SIZE, MAX_VERTS_PER_CHUNK


_FOV = 200.0
_CX = 200.0
_CY = 120.0
_FOG_NEAR_M = 30.0
_FOG_FAR_M  = 140.0
_FOG_NEAR_D = int(_FOG_NEAR_M * 1024)
_FOG_FAR_D  = int(_FOG_FAR_M  * 1024)
_FOG_RANGE  = _FOG_FAR_D - _FOG_NEAR_D
_NEAR_PLANE_MM = 10000
_MAX_SCREEN_COORD = 2000
_MIN_FACE_AREA = 9

_USE_VIPER = (getattr(sys, "implementation", None) is not None and
              sys.implementation.name == "micropython")


if _USE_VIPER:

    @micropython.viper
    def _post_pass_viper(
            indices: ptr16, temp_verts: ptr32,
            out_poly: ptr16, depths: ptr32, dither: ptr8,
            n_faces: int,
            near_pl_mm: int,
            max_sc: int, neg_sc: int,
            fog_near_d: int, fog_far_d: int, fog_range: int,
            min_area: int):
        i = 0
        while i < n_faces:
            d = int(dither[i])
            if d == 255:
                i += 1
                continue
            # TEST: clamp d=0 to d=1. If the brightest-lit faces stop
            # disappearing with this clamp, the deck treats dither=0
            # as "skip face entirely" rather than "draw with zero
            # foreground pixels". The fix would then be to apply this
            # clamp permanently, plus floor the fog math at 1.
            if d == 0:
                d = 1
                dither[i] = 1
            i3 = i * 3
            v0 = int(indices[i3])
            v1 = int(indices[i3 + 1])
            v2 = int(indices[i3 + 2])
            z0 = int(temp_verts[v0 * 3 + 2])
            z1 = int(temp_verts[v1 * 3 + 2])
            z2 = int(temp_verts[v2 * 3 + 2])
            if z0 < near_pl_mm:
                dither[i] = 255
                i += 1
                continue
            if z1 < near_pl_mm:
                dither[i] = 255
                i += 1
                continue
            if z2 < near_pl_mm:
                dither[i] = 255
                i += 1
                continue
            i6 = i * 6
            x0c = int(out_poly[i6 + 0])
            if x0c >= 32768: x0c = x0c - 65536
            x1c = int(out_poly[i6 + 1])
            if x1c >= 32768: x1c = x1c - 65536
            x2c = int(out_poly[i6 + 2])
            if x2c >= 32768: x2c = x2c - 65536
            y0c = int(out_poly[i6 + 3])
            if y0c >= 32768: y0c = y0c - 65536
            y1c = int(out_poly[i6 + 4])
            if y1c >= 32768: y1c = y1c - 65536
            y2c = int(out_poly[i6 + 5])
            if y2c >= 32768: y2c = y2c - 65536
            if x0c > max_sc or x0c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            if x1c > max_sc or x1c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            if x2c > max_sc or x2c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            if y0c > max_sc or y0c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            if y1c > max_sc or y1c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            if y2c > max_sc or y2c < neg_sc:
                dither[i] = 255
                i += 1
                continue
            xmin = x0c
            if x1c < xmin: xmin = x1c
            if x2c < xmin: xmin = x2c
            xmax = x0c
            if x1c > xmax: xmax = x1c
            if x2c > xmax: xmax = x2c
            ymin = y0c
            if y1c < ymin: ymin = y1c
            if y2c < ymin: ymin = y2c
            ymax = y0c
            if y1c > ymax: ymax = y1c
            if y2c > ymax: ymax = y2c
            if (xmax - xmin) * (ymax - ymin) < min_area:
                dither[i] = 255
                i += 1
                continue
            z = int(depths[i])
            if z >= fog_far_d:
                dither[i] = 255
                i += 1
                continue
            if z > fog_near_d:
                t_q8 = ((z - fog_near_d) * 256) // fog_range
                t2_q8 = (t_q8 * t_q8) >> 8
                scale_q8 = 256 - t2_q8
                new_d = (d * scale_q8) >> 8
                if new_d <= 0:
                    dither[i] = 255
                else:
                    dither[i] = new_d
            i += 1


    @micropython.native
    def _prep_z(temp_verts, verts_z_mm, n_verts):
        for i in range(n_verts):
            verts_z_mm[i * 3 + 2] = int(temp_verts[i * 3 + 2] * 1000.0)


def _post_pass_py(indices, temp_verts_i, out_poly, depths, dither,
                  n_faces, near_pl_mm, max_sc, neg_sc,
                  fog_near_d, fog_far_d, fog_range, min_area):
    for i in range(n_faces):
        d = dither[i]
        if d < 0:
            continue
        if d == 0:
            d = 1
            dither[i] = 1
        i3 = i * 3
        v0 = indices[i3]
        v1 = indices[i3 + 1]
        v2 = indices[i3 + 2]
        if (temp_verts_i[v0 * 3 + 2] < near_pl_mm or
            temp_verts_i[v1 * 3 + 2] < near_pl_mm or
            temp_verts_i[v2 * 3 + 2] < near_pl_mm):
            dither[i] = -1
            continue
        i6 = i * 6
        x0c = out_poly[i6 + 0]
        x1c = out_poly[i6 + 1]
        x2c = out_poly[i6 + 2]
        y0c = out_poly[i6 + 3]
        y1c = out_poly[i6 + 4]
        y2c = out_poly[i6 + 5]
        if (x0c > max_sc or x0c < neg_sc or
            x1c > max_sc or x1c < neg_sc or
            x2c > max_sc or x2c < neg_sc or
            y0c > max_sc or y0c < neg_sc or
            y1c > max_sc or y1c < neg_sc or
            y2c > max_sc or y2c < neg_sc):
            dither[i] = -1
            continue
        xmin = x0c if x0c < x1c else x1c
        if x2c < xmin: xmin = x2c
        xmax = x0c if x0c > x1c else x1c
        if x2c > xmax: xmax = x2c
        ymin = y0c if y0c < y1c else y1c
        if y2c < ymin: ymin = y2c
        ymax = y0c if y0c > y1c else y1c
        if y2c > ymax: ymax = y2c
        if (xmax - xmin) * (ymax - ymin) < min_area:
            dither[i] = -1
            continue
        z = depths[i]
        if z >= fog_far_d:
            dither[i] = -1
            continue
        if z > fog_near_d:
            t_q8 = ((z - fog_near_d) * 256) // fog_range
            t2_q8 = (t_q8 * t_q8) >> 8
            scale_q8 = 256 - t2_q8
            new_d = (d * scale_q8) >> 8
            if new_d <= 0:
                dither[i] = -1
            else:
                dither[i] = new_d


def _prep_z_py(temp_verts, n_verts, temp_verts_i):
    for i in range(n_verts):
        temp_verts_i[i * 3 + 2] = int(temp_verts[i * 3 + 2] * 1000.0)


class CityDemo:

  def __init__(self, vscreen):
    self.v = vscreen
    self.last_us = time.ticks_us()
    self.camera = Camera()
    self.grid = ChunkGrid()
    self.matrix = array.array('f', [0.0] * 16)
    # Asymmetric light. Looks better than a centered light; produces
    # contrast between the visible faces of buildings. Known edge case:
    # at certain bright-face geometries the lighting computation can
    # produce visible artifacts (face disappearance at extreme bright
    # angles). The dither=0 -> 1 clamp in _post_pass mitigates some
    # but not all of those cases.
    self.light = array.array('f', [0.5, 0.7, -1.0])
    self._fps_ema = 30.0
    self._visible_chunks = 0
    self._visible_faces = 0
    self._visible_list = []
    self._verts_z_mm = array.array('i', [0] * (MAX_VERTS_PER_CHUNK * 3))
    self._neg_max_sc = -_MAX_SCREEN_COORD

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
      if _USE_VIPER:
        _prep_z(ch.temp_verts, self._verts_z_mm, ch.n_verts)
      else:
        _prep_z_py(ch.temp_verts, ch.n_verts, self._verts_z_mm)
      if _USE_VIPER:
        _post_pass_viper(
          ch.indices, self._verts_z_mm,
          ch.out_poly, ch.depths, ch.out_dither,
          ch.n_faces,
          _NEAR_PLANE_MM,
          _MAX_SCREEN_COORD, self._neg_max_sc,
          _FOG_NEAR_D, _FOG_FAR_D, _FOG_RANGE,
          _MIN_FACE_AREA,
        )
      else:
        _post_pass_py(
          ch.indices, self._verts_z_mm,
          ch.out_poly, ch.depths, ch.out_dither,
          ch.n_faces,
          _NEAR_PLANE_MM,
          _MAX_SCREEN_COORD, self._neg_max_sc,
          _FOG_NEAR_D, _FOG_FAR_D, _FOG_RANGE,
          _MIN_FACE_AREA,
        )
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

    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(5, 12, "CITY  {:.0f} FPS  FACES {}".format(
      self._fps_ema, self._visible_faces))

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
