"""Chunk grid: deterministic infinite city via tile-based generation.

The world is divided into square chunks (CHUNK_SIZE on a side). Each
chunk is a (cx, cz) integer cell coordinate. Chunk contents are
generated deterministically from hash(cx, cz) — revisiting the same
coords always yields the same skyline, with zero state to persist.

A sliding window of (2*RADIUS+1)^2 chunks is kept resident around the
camera. As the camera crosses a chunk boundary, new chunks are baked
and old ones evicted. Each resident chunk owns one welded mesh
(verts/indices/normals + per-frame projection-output buffers) so the
renderer can draw the whole chunk in a single project_3d_indexed call.

M3: each lot is one of three archetypes (regular / slab / stepped).
Stepped buildings use two boxes (24 faces) so buffer capacity is sized
to the worst case.
"""

import array

from .buildings import (
  REG_W_MIN, REG_W_MAX, REG_H_MIN, REG_H_MAX, REG_D_MIN, REG_D_MAX,
  SLAB_W_MIN, SLAB_W_MAX, SLAB_H_MIN, SLAB_H_MAX, SLAB_D_MIN, SLAB_D_MAX,
  STEP_BASE_W_MIN, STEP_BASE_W_MAX, STEP_BASE_H_MIN, STEP_BASE_H_MAX,
  STEP_BASE_D_MIN, STEP_BASE_D_MAX,
  STEP_UPPER_SHRINK_MIN, STEP_UPPER_SHRINK_MAX,
  STEP_UPPER_H_MIN, STEP_UPPER_H_MAX,
  FACES_PER_BOX, VERTS_PER_BOX, MAX_BOXES_PER_BUILDING,
  bake_building,
)


# World layout
CHUNK_SIZE = 60.0
RADIUS = 2                 # 5x5 resident window
BUILDINGS_PER_CHUNK = 6    # reduced from M2's 7 to fit stepped variant budget

# Archetype probabilities. Sum to 1.0; sampled per lot.
P_REGULAR = 0.60
P_SLAB    = 0.25
P_STEPPED = 0.15           # P_REGULAR + P_SLAB + P_STEPPED = 1.0

# Per-chunk worst-case capacity. Allocated upfront; baker writes <= this.
MAX_FACES_PER_CHUNK = BUILDINGS_PER_CHUNK * FACES_PER_BOX * MAX_BOXES_PER_BUILDING
MAX_VERTS_PER_CHUNK = BUILDINGS_PER_CHUNK * VERTS_PER_BOX * MAX_BOXES_PER_BUILDING


def _hash(cx, cz, salt=0):
  """Deterministic 32-bit hash of integer chunk coords + salt."""
  zx = (cx << 1) ^ (cx >> 31)
  zz = (cz << 1) ^ (cz >> 31)
  h = (zx * 73856093) ^ (zz * 19349663) ^ (salt * 83492791)
  h = h & 0x7FFFFFFF
  h ^= h >> 17
  h = (h * 2246822519) & 0x7FFFFFFF
  h ^= h >> 13
  return h


class _RNG:
  """Tiny xorshift32 RNG seeded from chunk hash."""

  __slots__ = ('s',)

  def __init__(self, seed):
    self.s = seed | 1

  def next(self):
    s = self.s
    s ^= (s << 13) & 0xFFFFFFFF
    s ^= (s >> 17)
    s ^= (s << 5) & 0xFFFFFFFF
    self.s = s & 0xFFFFFFFF
    return self.s

  def frange(self, lo, hi):
    u = (self.next() >> 8) * (1.0 / 16777216.0)
    return lo + (hi - lo) * u


class Chunk:
  """One resident chunk: baked mesh + projection output buffers."""

  __slots__ = (
    'cx', 'cz', 'cx_world', 'cz_world',
    'n_verts', 'n_faces',
    'verts', 'indices', 'normals',
    'out_poly', 'out_dither', 'depths',
    'temp_verts', 'temp_norms', 'sort_idx',
  )

  def __init__(self):
    self.cx = 0
    self.cz = 0
    self.cx_world = 0.0
    self.cz_world = 0.0
    self.n_verts = 0
    self.n_faces = 0
    self.verts   = array.array('f', [0.0] * (MAX_VERTS_PER_CHUNK * 3))
    self.indices = array.array('H', [0]   * (MAX_FACES_PER_CHUNK * 3))
    self.normals = array.array('f', [0.0] * (MAX_FACES_PER_CHUNK * 3))
    self.out_poly   = array.array('h', [0] * (MAX_FACES_PER_CHUNK * 6))
    self.out_dither = array.array('b', [0] * MAX_FACES_PER_CHUNK)
    self.depths     = array.array('i', [0] * MAX_FACES_PER_CHUNK)
    self.temp_verts = array.array('f', [0.0] * (MAX_VERTS_PER_CHUNK * 3))
    self.temp_norms = array.array('f', [0.0] * (MAX_FACES_PER_CHUNK * 3))
    self.sort_idx   = array.array('H', [0] * MAX_FACES_PER_CHUNK)

  def bake(self, cx, cz):
    """Generate this chunk's geometry deterministically.

    For each lot in the chunk's 4x4 sub-grid, pick an archetype
    (regular / slab / stepped) and call bake_building one or two times.
    """
    self.cx = cx
    self.cz = cz
    self.cx_world = cx * CHUNK_SIZE
    self.cz_world = cz * CHUNK_SIZE

    rng = _RNG(_hash(cx, cz, salt=1))
    half = CHUNK_SIZE * 0.5
    x0 = self.cx_world - half
    z0 = self.cz_world - half

    GRID = 4
    cell = CHUNK_SIZE / GRID
    slots = [(i, j) for i in range(GRID) for j in range(GRID)]
    n_slots = len(slots)
    for k in range(min(BUILDINGS_PER_CHUNK, n_slots)):
      j = k + (rng.next() % (n_slots - k))
      slots[k], slots[j] = slots[j], slots[k]

    vi = 0; ii = 0; ni = 0; vert_offset = 0
    for k in range(BUILDINGS_PER_CHUNK):
      gi, gj = slots[k]
      jx = rng.frange(-0.10, 0.10) * cell
      jz = rng.frange(-0.10, 0.10) * cell
      bx = x0 + (gi + 0.5) * cell + jx
      bz = z0 + (gj + 0.5) * cell + jz

      r = rng.frange(0.0, 1.0)
      if r < P_REGULAR:
        # Regular box. Height biased shorter via u^2.
        w = rng.frange(REG_W_MIN, REG_W_MAX)
        d = rng.frange(REG_D_MIN, REG_D_MAX)
        u = rng.frange(0.0, 1.0)
        h = REG_H_MIN + (REG_H_MAX - REG_H_MIN) * u * u
        vi, ii, ni, vert_offset = bake_building(
          self.verts, self.indices, self.normals,
          vi, ii, ni, vert_offset,
          bx, 0.0, bz, w, h, d,
        )
      elif r < P_REGULAR + P_SLAB:
        # Tall narrow slab.
        w = rng.frange(SLAB_W_MIN, SLAB_W_MAX)
        d = rng.frange(SLAB_D_MIN, SLAB_D_MAX)
        h = rng.frange(SLAB_H_MIN, SLAB_H_MAX)
        vi, ii, ni, vert_offset = bake_building(
          self.verts, self.indices, self.normals,
          vi, ii, ni, vert_offset,
          bx, 0.0, bz, w, h, d,
        )
      else:
        # Stepped: base box plus smaller upper box on top.
        bw = rng.frange(STEP_BASE_W_MIN, STEP_BASE_W_MAX)
        bd = rng.frange(STEP_BASE_D_MIN, STEP_BASE_D_MAX)
        bh = rng.frange(STEP_BASE_H_MIN, STEP_BASE_H_MAX)
        vi, ii, ni, vert_offset = bake_building(
          self.verts, self.indices, self.normals,
          vi, ii, ni, vert_offset,
          bx, 0.0, bz, bw, bh, bd,
        )
        # Upper box: shrunk W/D, stacked at y = bh
        shrink = rng.frange(STEP_UPPER_SHRINK_MIN, STEP_UPPER_SHRINK_MAX)
        uw = bw * shrink
        ud = bd * shrink
        uh = rng.frange(STEP_UPPER_H_MIN, STEP_UPPER_H_MAX)
        vi, ii, ni, vert_offset = bake_building(
          self.verts, self.indices, self.normals,
          vi, ii, ni, vert_offset,
          bx, bh, bz, uw, uh, ud,
        )

    self.n_verts = vert_offset
    self.n_faces = ii // 3


class ChunkGrid:
  """Manages the resident set of chunks around the camera."""

  def __init__(self):
    self.chunks = {}
    self._free = []
    self._last_cam_cell = None

    n = (2 * RADIUS + 1) ** 2
    for _ in range(n):
      self._free.append(Chunk())

  def _cell_for(self, x, z):
    return (int(x // CHUNK_SIZE), int(z // CHUNK_SIZE))

  def update(self, cam_x, cam_z):
    cell = self._cell_for(cam_x, cam_z)
    if cell == self._last_cam_cell:
      return
    self._last_cam_cell = cell
    ccx, ccz = cell

    needed = set()
    for dcx in range(-RADIUS, RADIUS + 1):
      for dcz in range(-RADIUS, RADIUS + 1):
        needed.add((ccx + dcx, ccz + dcz))

    stale = [key for key in self.chunks if key not in needed]
    for key in stale:
      ch = self.chunks.pop(key)
      self._free.append(ch)

    for key in needed:
      if key in self.chunks:
        continue
      ch = self._free.pop()
      ch.bake(key[0], key[1])
      self.chunks[key] = ch

  def visible(self, cam_x, cam_z, forward_x, forward_z):
    """Yield chunks plausibly visible from camera (forward-hemisphere)."""
    for ch in self.chunks.values():
      dx = ch.cx_world - cam_x
      dz = ch.cz_world - cam_z
      if dx * forward_x + dz * forward_z > -CHUNK_SIZE:
        yield ch
