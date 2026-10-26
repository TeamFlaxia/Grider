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
