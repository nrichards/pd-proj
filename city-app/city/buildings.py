"""Building geometry: axis-aligned boxes with three archetypes.

Each building is composed of one or more boxes. A single box is 8 vertices
and 12 faces. The bake_building() function appends one box's geometry into
pre-allocated flat arrays. For stepped buildings, the caller invokes
bake_building twice (lower + upper) at the same lot center.

Three archetypes are used by chunks.py:
  - "regular": one box with moderate W/H/D
  - "slab":    one box, narrow W/D, tall H (skyscraper-like)
  - "stepped": two boxes stacked, upper smaller in W/D

Archetype selection is the chunk's responsibility; this module just
provides the primitive.
"""

# Regular building ranges (world units = meters)
REG_W_MIN = 8.0
REG_W_MAX = 16.0
REG_H_MIN = 8.0
REG_H_MAX = 28.0
REG_D_MIN = 8.0
REG_D_MAX = 16.0

# Slab (narrow tall tower)
SLAB_W_MIN = 5.0
SLAB_W_MAX = 9.0
SLAB_H_MIN = 40.0
SLAB_H_MAX = 75.0
SLAB_D_MIN = 5.0
SLAB_D_MAX = 9.0

# Stepped (lower base, upper smaller cap)
STEP_BASE_W_MIN = 10.0
STEP_BASE_W_MAX = 16.0
STEP_BASE_H_MIN = 15.0
STEP_BASE_H_MAX = 30.0
STEP_BASE_D_MIN = 10.0
STEP_BASE_D_MAX = 16.0
STEP_UPPER_SHRINK_MIN = 0.45  # upper W/D = base W/D * shrink
STEP_UPPER_SHRINK_MAX = 0.75
STEP_UPPER_H_MIN = 10.0
STEP_UPPER_H_MAX = 25.0


# Box topology: 8 vertices, 12 triangles. Winding produces outward normals.
# Vertex layout: 0-3 at z = z_center - d/2 (near face),
#                4-7 at z = z_center + d/2 (far face).
_BOX_FACE_INDICES = (
  (0, 1, 2), (2, 3, 0),  # near  (-Z)
  (1, 5, 6), (6, 2, 1),  # right (+X)
  (7, 6, 5), (5, 4, 7),  # far   (+Z)
  (4, 0, 3), (3, 7, 4),  # left  (-X)
  (4, 5, 1), (1, 0, 4),  # bottom (-Y)
  (3, 2, 6), (6, 7, 3),  # top   (+Y)
)
_NORMALS_PER_SIDE = (
  ( 0.0,  0.0, -1.0),
  ( 1.0,  0.0,  0.0),
  ( 0.0,  0.0,  1.0),
  (-1.0,  0.0,  0.0),
  ( 0.0, -1.0,  0.0),
  ( 0.0,  1.0,  0.0),
)

FACES_PER_BOX = len(_BOX_FACE_INDICES)  # 12
VERTS_PER_BOX = 8
MAX_BOXES_PER_BUILDING = 2  # stepped archetype


def bake_building(verts, indices, normals,
                  vi, ii, ni, vert_offset,
                  x, y, z, w, h, d):
  """Append one box's geometry to flat arrays.

  Args:
    verts:    array('f') of (x, y, z) per vertex
    indices:  array('H') of (i, j, k) per face
    normals:  array('f') of (nx, ny, nz) per face
    vi, ii, ni:   current write positions
    vert_offset:  index offset for this box's faces
    x, y, z:      box base-center (y = bottom face Y)
    w, h, d:      width (X), height (Y), depth (Z)

  Returns: (new_vi, new_ii, new_ni, new_vert_offset)
  """
  hw = w * 0.5
  hd = d * 0.5

  verts[vi+0]  = x - hw; verts[vi+1]  = y;     verts[vi+2]  = z - hd
  verts[vi+3]  = x + hw; verts[vi+4]  = y;     verts[vi+5]  = z - hd
  verts[vi+6]  = x + hw; verts[vi+7]  = y + h; verts[vi+8]  = z - hd
  verts[vi+9]  = x - hw; verts[vi+10] = y + h; verts[vi+11] = z - hd
  verts[vi+12] = x - hw; verts[vi+13] = y;     verts[vi+14] = z + hd
  verts[vi+15] = x + hw; verts[vi+16] = y;     verts[vi+17] = z + hd
  verts[vi+18] = x + hw; verts[vi+19] = y + h; verts[vi+20] = z + hd
  verts[vi+21] = x - hw; verts[vi+22] = y + h; verts[vi+23] = z + hd
  vi += 24

  for f_idx in range(FACES_PER_BOX):
    a, b, c = _BOX_FACE_INDICES[f_idx]
    indices[ii]   = vert_offset + a
    indices[ii+1] = vert_offset + b
    indices[ii+2] = vert_offset + c
    ii += 3
    side = f_idx // 2
    nx, ny, nz = _NORMALS_PER_SIDE[side]
    normals[ni]   = nx
    normals[ni+1] = ny
    normals[ni+2] = nz
    ni += 3

  return vi, ii, ni, vert_offset + VERTS_PER_BOX
