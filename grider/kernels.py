# SPDX-License-Identifier: Apache-2.0

"""Dependency-free reference implementations for common AI kernels.

These are algorithmic oracles for kernel mappings. They use Python lists and
float64 host arithmetic; quantized/cycle-accurate behavior is provided by the
tile simulator and its explicitly typed instructions.
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


def matmul(a: Matrix, b: Matrix) -> list[list[float]]:
    """Reference dense matrix multiplication (M×K by K×N)."""
    rows, inner = _shape(a, "a")
    b_rows, cols = _shape(b, "b")
    if inner != b_rows:
        raise ValueError(f"incompatible matmul shapes {(rows, inner)} and {(b_rows, cols)}")
    bt = list(zip(*b))
    return [[math.fsum(float(x) * float(y) for x, y in zip(row, col))
             for col in bt] for row in a]


def softmax_rows(x: Matrix, *, causal: bool = False) -> list[list[float]]:
    """Stable row-wise softmax; causal mode masks future columns per row."""
    rows, cols = _shape(x, "x")
    out: list[list[float]] = []
    for r, row in enumerate(x):
        stop = min(cols, r + 1) if causal else cols
        if stop == 0:
            out.append([0.0] * cols)
            continue
        visible = [float(v) for v in row[:stop]]
        maximum = max(visible)
        numerators = [math.exp(v - maximum) for v in visible]
        total = math.fsum(numerators)
        out.append([v / total for v in numerators] + [0.0] * (cols - stop))
    return out


def layer_norm(x: Matrix, scale: Sequence[float] | None = None,
               bias: Sequence[float] | None = None, *, eps: float = 1e-5) -> list[list[float]]:
    """Normalize each row over its features with optional affine parameters."""
    rows, cols = _shape(x, "x")
    if eps <= 0:
        raise ValueError("eps must be positive")
    if scale is not None and len(scale) != cols:
        raise ValueError("scale length must match feature count")
    if bias is not None and len(bias) != cols:
        raise ValueError("bias length must match feature count")
    result: list[list[float]] = []
    for row in x:
        values = [float(v) for v in row]
        mean = math.fsum(values) / cols
        variance = math.fsum((v - mean) ** 2 for v in values) / cols
        inv_std = 1.0 / math.sqrt(variance + eps)
        normalized = [(v - mean) * inv_std for v in values]
        if scale is not None:
            normalized = [v * float(g) for v, g in zip(normalized, scale)]
        if bias is not None:
            normalized = [v + float(b) for v, b in zip(normalized, bias)]
        result.append(normalized)
    return result


def scaled_dot_product_attention(q: Matrix, k: Matrix, v: Matrix, *,
                                 causal: bool = False) -> list[list[float]]:
    """Single-head scaled dot-product attention: softmax(QKᵀ/√d) V."""
    q_rows, dim = _shape(q, "q")
    k_rows, k_dim = _shape(k, "k")
    v_rows, value_dim = _shape(v, "v")
    if dim != k_dim or k_rows != v_rows:
        raise ValueError("q/k feature widths and k/v sequence lengths must match")
    kt = list(zip(*k))
    scale = 1.0 / math.sqrt(dim)
    scores = [[math.fsum(float(x) * float(y) for x, y in zip(qr, kc)) * scale
               for kc in kt] for qr in q]
    weights = softmax_rows(scores, causal=causal)
    vt = list(zip(*v))
    return [[math.fsum(float(w) * float(x) for w, x in zip(weight, column))
             for column in vt] for weight in weights]


def gelu(x: Matrix) -> list[list[float]]:
    """GELU activation using the common tanh approximation."""
    _shape(x, "x")
    scale = math.sqrt(2.0 / math.pi)
    return [[0.5 * float(v) * (1.0 + math.tanh(scale * (float(v) + 0.044715 * float(v) ** 3)))
             for v in row] for row in x]


def rms_norm(x: Matrix, weight: Sequence[float] | None = None,
             *, eps: float = 1e-6) -> list[list[float]]:
    """Root-mean-square normalization per row (Llama/Qwen style)."""
    rows, cols = _shape(x, "x")
    if eps <= 0:
        raise ValueError("eps must be positive")
    if weight is not None and len(weight) != cols:
        raise ValueError("weight length must match feature count")
    result: list[list[float]] = []
    for row in x:
        values = [float(v) for v in row]
        mean_square = math.fsum(v * v for v in values) / cols
        inv = 1.0 / math.sqrt(mean_square + eps)
        normalized = [v * inv for v in values]
        if weight is not None:
            normalized = [v * float(w) for v, w in zip(normalized, weight)]
        result.append(normalized)
    return result


def silu(x: Matrix) -> list[list[float]]:
    """SiLU/Swish activation: x / (1 + exp(-x))."""
    _shape(x, "x")
    return [[float(v) / (1.0 + math.exp(-float(v))) for v in row] for row in x]


def swiglu_gate(gate: Matrix, value: Matrix) -> list[list[float]]:
    """SwiGLU: silu(gate) * value."""
    shape_g = _shape(gate, "gate")
    shape_v = _shape(value, "value")
    if shape_g != shape_v:
        raise ValueError("gate and value must have the same shape")
    activated = silu(gate)
    return [[float(g) * float(v) for g, v in zip(row_g, row_v)]
            for row_g, row_v in zip(activated, value)]


def rope(x: Matrix, positions: Sequence[int] | None = None,
         base: float = 10000.0) -> list[list[float]]:
    """Rotary positional embedding (RoPE) applied per row.

    Pairs of adjacent features are rotated by angle = pos / base**(2i/d).
    If positions is None, row index is used.
    """
    rows, cols = _shape(x, "x")
    if cols % 2 != 0:
        raise ValueError("rope requires an even feature width")
    if positions is not None and len(positions) != rows:
        raise ValueError("positions length must match row count")
    out: list[list[float]] = []
    for r, row in enumerate(x):
        pos = float(positions[r] if positions is not None else r)
        rotated: list[float] = []
        for i in range(0, cols, 2):
            freq = 1.0 / (base ** ((i) / cols))
            angle = pos * freq
            c = math.cos(angle)
            s = math.sin(angle)
            a = float(row[i])
            b = float(row[i + 1])
            rotated.append(a * c - b * s)
            rotated.append(a * s + b * c)
        out.append(rotated)
    return out


def conv2d(x: Matrix, kernel: Matrix) -> list[list[float]]:
    """2D convolution with zero padding, valid output."""
    rows, cols = _shape(x, "x")
    krows, kcols = _shape(kernel, "kernel")
    if krows % 2 == 0 or kcols % 2 == 0:
        raise ValueError("conv2d kernel must be odd-sized")
    pad_r = krows // 2
    pad_c = kcols // 2
    out: list[list[float]] = []
    for r in range(rows):
        out_row: list[float] = []
        for c in range(cols):
            acc = 0.0
            for kr in range(krows):
                for kc in range(kcols):
                    sr = r + kr - pad_r
                    sc = c + kc - pad_c
                    if 0 <= sr < rows and 0 <= sc < cols:
                        acc += float(x[sr][sc]) * float(kernel[kr][kc])
            out_row.append(acc)
        out.append(out_row)
    return out


def histogram_rows(x: Matrix, bins: int) -> list[list[int]]:
    """Per-row histogram of values via min/max quantization."""
    rows, cols = _shape(x, "x")
    if bins < 1:
        raise ValueError("bins must be positive")
    result: list[list[int]] = []
    for row in x:
        values = [float(v) for v in row]
        lo = min(values)
        hi = max(values)
        if hi == lo:
            counts = [0] * bins
            counts[0] = cols
            result.append(counts)
            continue
        counts = [0] * bins
        for v in values:
            idx = int((v - lo) / (hi - lo) * bins)
            if idx >= bins:
                idx = bins - 1
            counts[idx] += 1
        result.append(counts)
    return result


def topk_rows(x: Matrix, k: int) -> list[list[float]]:
    """Per-row top-k values sorted descending."""
    rows, cols = _shape(x, "x")
    if not 1 <= k <= cols:
        raise ValueError("k must be in [1, ncols]")
    return [sorted((float(v) for v in row), reverse=True)[:k] for row in x]
