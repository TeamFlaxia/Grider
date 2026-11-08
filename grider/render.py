# SPDX-License-Identifier: Apache-2.0

"""Dependency-free rendering reference kernels for tile dataflow planning.

These are host-side oracles for per-pixel raster/shading/blending math. They
use Python lists and float64 arithmetic; cycle-accurate behavior is provided by
the tile simulator and its typed instructions (F32 elementwise, DOT_ROW for
lighting dot products, TRANSPOSE for transforms, NEIGHBOR stencils).
"""

from __future__ import annotations

import math
from typing import Sequence

Matrix = Sequence[Sequence[float]]


def _shape(matrix: Matrix, name: str) -> tuple[int, int]:
    if not matrix or not matrix[0]:
        raise ValueError(f"{name} must be non-empty")
    cols = len(matrix[0])
    if any(len(row) != cols for row in matrix):
        raise ValueError(f"{name} must be rectangular")
    return len(matrix), cols


def box_blur(x: Matrix, radius: int = 1) -> list[list[float]]:
    """Separable 3x3-style box blur with clamped borders."""
    rows, cols = _shape(x, "x")
    if radius < 0:
        raise ValueError("radius must be non-negative")
    out: list[list[float]] = []
    for r in range(rows):
        row_out: list[float] = []
        for c in range(cols):
            total = 0.0
            count = 0
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    rr = min(max(r + dr, 0), rows - 1)
                    cc = min(max(c + dc, 0), cols - 1)
                    total += float(x[rr][cc])
                    count += 1
            row_out.append(total / max(1, count))
        out.append(row_out)
    return out


def sobel_edge(x: Matrix) -> list[list[float]]:
    """Sobel gradient magnitude (edge strength)."""
    rows, cols = _shape(x, "x")
    gx_kernel = [[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]]
    gy_kernel = [[-1.0, -2.0, -1.0], [0.0, 0.0, 0.0], [1.0, 2.0, 1.0]]

    def convolve(kernel: list[list[float]]) -> list[list[float]]:
        out = [[0.0] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                acc = 0.0
                for kr in (-1, 0, 1):
                    for kc in (-1, 0, 1):
                        rr = r + kr
                        cc = c + kc
                        if 0 <= rr < rows and 0 <= cc < cols:
                            acc += float(x[rr][cc]) * kernel[kr + 1][kc + 1]
                out[r][c] = acc
        return out

    gx = convolve(gx_kernel)
    gy = convolve(gy_kernel)
    return [[math.hypot(gx[r][c], gy[r][c]) for c in range(cols)] for r in range(rows)]


def bilinear_sample(texture: Matrix, u: float, v: float) -> float:
    """Bilinear sample of a texture at normalized (u, v) in [0, 1)."""
    rows, cols = _shape(texture, "texture")
    if rows == 1 and cols == 1:
        return float(texture[0][0])
    x = min(max(u, 0.0), 0.9999999) * cols - 0.5
    y = min(max(v, 0.0), 0.9999999) * rows - 0.5
    x0 = math.floor(x)
    y0 = math.floor(y)
    fx = x - x0
    fy = y - y0

    def texel(rr: int, cc: int) -> float:
        rr = min(max(rr, 0), rows - 1)
        cc = min(max(cc, 0), cols - 1)
        return float(texture[rr][cc])

    top = texel(y0, x0) * (1.0 - fx) + texel(y0, x0 + 1) * fx
    bottom = texel(y0 + 1, x0) * (1.0 - fx) + texel(y0 + 1, x0 + 1) * fx
    return top * (1.0 - fy) + bottom * fy


def alpha_blend(fg: Matrix, bg: Matrix, alpha: Matrix) -> list[list[float]]:
    """Per-pixel alpha blend: fg*a + bg*(1-a), alpha in [0,1]."""
    shape = _shape(fg, "fg")
    if _shape(bg, "bg") != shape or _shape(alpha, "alpha") != shape:
        raise ValueError("fg/bg/alpha must have the same shape")
    rows, cols = shape
    return [[float(fg[r][c]) * float(alpha[r][c]) +
             float(bg[r][c]) * (1.0 - float(alpha[r][c]))
             for c in range(cols)] for r in range(rows)]


def barycentric(px: float, py: float,
                p0: tuple[float, float], p1: tuple[float, float],
                p2: tuple[float, float]) -> tuple[float, float, float] | None:
    """Barycentric coordinates of pixel (px, py) in triangle; None if degenerate."""
    denom = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
    if denom == 0.0:
        return None
    inv = 1.0 / denom
    w0 = ((p1[1] - p2[1]) * (px - p2[0]) + (p2[0] - p1[0]) * (py - p2[1])) * inv
    w1 = ((p2[1] - p0[1]) * (px - p2[0]) + (p0[0] - p2[0]) * (py - p2[1])) * inv
    w2 = 1.0 - w0 - w1
    return (w0, w1, w2)


def lambert(normal: tuple[float, float, float],
            light_dir: tuple[float, float, float],
            albedo: float) -> float:
    """Lambertian diffuse: albedo * max(0, dot(N, L))."""
    n_len = math.sqrt(sum(v * v for v in normal))
    l_len = math.sqrt(sum(v * v for v in light_dir))
    if n_len == 0.0 or l_len == 0.0:
        return 0.0
    dot = sum(n * l for n, l in zip(normal, light_dir)) / (n_len * l_len)
    return float(albedo) * max(0.0, dot)


def perspective_divide(x: float, y: float, w: float) -> tuple[float, float]:
    """Perspective divide (x/w, y/w); w==0 yields zeros."""
    if w == 0.0:
        return (0.0, 0.0)
    return (x / w, y / w)


def resize_bilinear(x: Matrix, out_rows: int, out_cols: int) -> list[list[float]]:
    """Nearest-center-aligned bilinear resize."""
    rows, cols = _shape(x, "x")
    if out_rows < 1 or out_cols < 1:
        raise ValueError("output size must be positive")
    out: list[list[float]] = []
    for r in range(out_rows):
        v = (r + 0.5) / out_rows
        row: list[float] = []
        for c in range(out_cols):
            u = (c + 0.5) / out_cols
            row.append(bilinear_sample(x, u, v))
        out.append(row)
    return out
