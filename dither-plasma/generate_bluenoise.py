#!/usr/bin/env python3
"""generate_bluenoise.py — produce a 64x64 blue noise threshold tile.

Implements Ulichney's void-and-cluster algorithm (1993) using a
Gaussian energy filter for cluster/void detection. Output is a tile of
threshold values 0..N-1 where N = w*h, suitable for ordered dithering.

The resulting tile has the property that for any threshold T in 0..N-1,
the binary pattern formed by {pixels with rank <= T} is "blue" — its
power spectrum is concentrated in high spatial frequencies and missing
from low ones. This is what makes blue noise visually pleasant compared
to Bayer (which has strong harmonic content at the matrix frequency).

Run on host (CPython, with numpy). Produces a Python module containing
the tile as a bytes literal, suitable for shipping as part of the
pocketdeck_dither package.

Usage:
    python3 generate_bluenoise.py > lib/bluenoise_tile.py

Generated output is original work; the algorithm is in the public
domain (Ulichney 1993, freely published). No copied data — the tile
this script produces is CC0/public domain by virtue of being freshly
computed from the algorithm.

Algorithm summary:
    1. Seed: place ~10% of pixels randomly as "1"s
    2. Cluster removal: repeatedly find the tightest cluster and
       relocate it to the largest void, until convergence. This gives
       us the "initial binary pattern" — already approximately blue.
    3. Phase 1: rank pixels from initial pattern down by removing the
       tightest cluster each iteration. The order of removal gives
       ranks N/2-1, N/2-2, ..., 0.
    4. Phase 2: rank pixels from initial pattern up by adding to the
       largest void each iteration. Order of addition gives ranks
       N/2, N/2+1, ..., N-1.
    5. Result: a w*h tile where each value 0..N-1 appears exactly once
       and is positioned to maintain blue-noise properties at every
       threshold level.
"""

import numpy as np
import sys
import time


def make_gaussian_filter(size, sigma=1.5):
    """Build a wrap-around Gaussian filter for energy computation.

    The filter kernel is the same size as the tile so that convolution
    via FFT is exact and toroidal — ensuring the resulting tile tiles
    seamlessly with itself.
    """
    # Build coordinates centered on (0, 0) with toroidal distance
    half = size // 2
    coords = np.arange(size)
    coords = np.minimum(coords, size - coords)  # toroidal distance from 0
    yy, xx = np.meshgrid(coords, coords, indexing='ij')
    d2 = xx * xx + yy * yy
    kernel = np.exp(-d2 / (2.0 * sigma * sigma))
    return kernel


def compute_energy(pattern, kernel_fft):
    """Convolve pattern with the Gaussian via FFT, returning the
    'energy' field. High energy = densely populated by 1s (cluster).
    Low energy where pattern is 1 = candidate void location to fill.
    """
    pattern_fft = np.fft.fft2(pattern.astype(np.float64))
    energy = np.real(np.fft.ifft2(pattern_fft * kernel_fft))
    return energy


def find_tightest_cluster(pattern, energy):
    """Index of the highest-energy 1-pixel — the tightest cluster."""
    # Mask out non-1 pixels by setting their energy to -inf
    masked = np.where(pattern == 1, energy, -np.inf)
    return np.unravel_index(np.argmax(masked), pattern.shape)


def find_largest_void(pattern, energy):
    """Index of the lowest-energy 0-pixel — the largest void."""
    masked = np.where(pattern == 0, energy, np.inf)
    return np.unravel_index(np.argmin(masked), pattern.shape)


def void_and_cluster(size=64, sigma=1.5, seed=42, verbose=True):
    """Full void-and-cluster algorithm. Returns tile of int ranks."""
    rng = np.random.default_rng(seed)
    n_pixels = size * size

    kernel = make_gaussian_filter(size, sigma)
    kernel_fft = np.fft.fft2(kernel)

    # ---- Step 1: seed pattern (~10% density) ----
    initial_count = max(1, n_pixels // 10)
    pattern = np.zeros((size, size), dtype=np.int8)
    flat_idx = rng.choice(n_pixels, size=initial_count, replace=False)
    for idx in flat_idx:
        pattern[idx // size, idx % size] = 1

    # ---- Step 2: clean the seed by repeatedly moving cluster -> void ----
    if verbose:
        print(f"# step 2: cleaning initial pattern", file=sys.stderr)
    for _ in range(initial_count):
        energy = compute_energy(pattern, kernel_fft)
        cluster = find_tightest_cluster(pattern, energy)
        pattern[cluster] = 0
        # Recompute energy with cluster removed
        energy = compute_energy(pattern, kernel_fft)
        void = find_largest_void(pattern, energy)
        if void == cluster:
            # Stable — moving the cluster to the same place. Restore and stop.
            pattern[cluster] = 1
            break
        pattern[void] = 1

    initial_pattern = pattern.copy()
    initial_ones = int(initial_pattern.sum())

    # The rank tile we're building
    ranks = np.zeros((size, size), dtype=np.int32)

    # ---- Phase 1: rank down from initial_ones-1 to 0 ----
    # Repeatedly remove the tightest cluster; that pixel gets the
    # next-lower rank.
    if verbose:
        print(f"# phase 1: ranking lower half ({initial_ones} pixels)",
              file=sys.stderr)
    pattern = initial_pattern.copy()
    for rank in range(initial_ones - 1, -1, -1):
        energy = compute_energy(pattern, kernel_fft)
        cluster = find_tightest_cluster(pattern, energy)
        ranks[cluster] = rank
        pattern[cluster] = 0

    # ---- Phase 2: rank up from initial_ones to n_pixels-1 ----
    # Repeatedly add to the largest void; that pixel gets the next rank.
    if verbose:
        print(f"# phase 2: ranking upper half ({n_pixels - initial_ones} pixels)",
              file=sys.stderr)
    pattern = initial_pattern.copy()
    for rank in range(initial_ones, n_pixels):
        energy = compute_energy(pattern, kernel_fft)
        void = find_largest_void(pattern, energy)
        ranks[void] = rank
        pattern[void] = 1

    return ranks


def ranks_to_thresholds(ranks):
    """Map int ranks 0..N-1 to byte thresholds 0..255.

    Linear remap: threshold = floor(rank * 256 / N). This gives an even
    distribution where each byte value 0..255 covers ceil(N/256) ranks.
    For a 64x64 tile that's N=4096 ranks mapped to 256 byte values =
    16 ranks per byte threshold.
    """
    n_pixels = ranks.size
    thresholds = (ranks.astype(np.int64) * 256 // n_pixels).astype(np.uint8)
    return thresholds


def emit_python_module(thresholds, sigma, seed, gen_time_s):
    """Print a Python module to stdout containing the tile as bytes."""
    h, w = thresholds.shape
    flat = thresholds.flatten().tobytes()

    print(f'''# bluenoise_tile.py
#
# 64x64 blue noise threshold tile, generated by void-and-cluster
# (Ulichney 1993) using a Gaussian energy filter.
#
# Generation parameters:
#   size:  {w}x{h}
#   sigma: {sigma}
#   seed:  {seed}
#   gen:   {gen_time_s:.1f}s on host
#
# License: CC0 / public domain. This file is original work generated
# by an algorithm in the public domain. The tile bytes are not copied
# from any external source.
#
# Tile properties:
#   - Each byte value 0..255 appears exactly {w * h // 256} times
#   - For any threshold T, the binary pattern {{pixels: byte <= T}} has
#     blue noise spectral character (high-frequency only)
#   - Tiles seamlessly with itself (toroidal generation)
#
# Usage:
#     from bluenoise_tile import TILE, TILE_SIZE
#     # ... pass to dither._blue_dither

TILE_SIZE = {w}
''')

    print('TILE = (')
    # Pretty-print as 16-byte rows
    bytes_per_line = 16
    for i in range(0, len(flat), bytes_per_line):
        chunk = flat[i:i + bytes_per_line]
        hex_str = ''.join(f'\\x{b:02x}' for b in chunk)
        print(f"    b'{hex_str}'")
    print(')')


def main():
    sigma = 1.5
    seed = 42
    size = 64

    t0 = time.time()
    ranks = void_and_cluster(size=size, sigma=sigma, seed=seed, verbose=True)
    elapsed = time.time() - t0

    # Sanity check: every rank 0..N-1 should appear exactly once
    n = size * size
    assert sorted(ranks.flatten().tolist()) == list(range(n)), \
        "ranks are not a permutation of 0..N-1"
    print(f"# generation complete: {elapsed:.1f}s, ranks valid",
          file=sys.stderr)

    thresholds = ranks_to_thresholds(ranks)
    emit_python_module(thresholds, sigma, seed, elapsed)


if __name__ == '__main__':
    main()
