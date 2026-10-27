"""Small instruction-stream kernels for the current Grider tile emulator.

The RTL has no program fetch unit. These helpers load host-prepared data,
assemble a bundled ``.gr`` program, and execute its instructions in ``Tile``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .asm import execute, load_kernel
from .sim import DataType, Tile, float_to_bf16

LANES = 16 * 16
FULL_MASK = (1 << LANES) - 1


def _check_vector(values: Sequence[int | float], name: str) -> None:
    if len(values) != LANES:
        raise ValueError(f"{name} must contain exactly {LANES} values")


def run_vector_add_bf16(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Run the bundled BF16 vector-add program across all 256 cells."""
    _check_vector(a, "a")
    _check_vector(b, "b")
    tile = Tile()
    tile.load_register(0, a, DataType.BF16)
    tile.load_register(1, b, DataType.BF16)
    execute(tile, load_kernel("vector_add_bf16"))
    return tile.read_register(2)


def run_row_sum_i32(values: Sequence[int], lane_mask: int = FULL_MASK) -> list[int]:
    """Run the bundled row-wise INT32 sum program across the tile."""
    _check_vector(values, "values")
    if not 0 <= lane_mask <= FULL_MASK:
        raise ValueError(f"lane_mask must fit in {LANES} bits")
    tile = Tile()
    tile.load_register(0, values, DataType.I32)
    program = load_kernel("row_sum_i32")
    if lane_mask != FULL_MASK:
        program = [replace(instruction, lane_mask=lane_mask) for instruction in program]
    execute(tile, program)
    return tile.read_register(2)


def _pack_bf16x8(values: Sequence[float]) -> int:
    if len(values) != 8:
        raise ValueError("a packed Grider word must contain eight BF16 values")
    word = 0
    for index, value in enumerate(values):
        word |= float_to_bf16(float(value)) << (16 * index)
    return word


def run_matmul16_bf16(a: Sequence[Sequence[float]],
                      b: Sequence[Sequence[float]]) -> list[list[float]]:
    """Run the 16x16 BF16 instruction kernel with host-prepacked operands.

    The host supplies each A row and B column packed into two 128-bit
    registers, replicated to the corresponding output cells. The kernel then
    extracts each BF16 element with shifts and accumulates with MAC.
    """
    if len(a) != 16 or any(len(row) != 16 for row in a):
        raise ValueError("a must be a 16x16 matrix")
    if len(b) != 16 or any(len(row) != 16 for row in b):
        raise ValueError("b must be a 16x16 matrix")

    packed_a0 = [0] * LANES
    packed_a1 = [0] * LANES
    packed_b0 = [0] * LANES
    packed_b1 = [0] * LANES
    for row in range(16):
        a_low = _pack_bf16x8(a[row][:8])
        a_high = _pack_bf16x8(a[row][8:])
        for col in range(16):
            lane = row * 16 + col
            packed_a0[lane] = a_low
            packed_a1[lane] = a_high
            packed_b0[lane] = _pack_bf16x8([b[k][col] for k in range(8)])
            packed_b1[lane] = _pack_bf16x8([b[k][col] for k in range(8, 16)])

    tile = Tile()
    for register, packed in enumerate((packed_a0, packed_a1, packed_b0, packed_b1)):
        tile.load_register(register, packed, DataType.U128)
    execute(tile, load_kernel("matmul16_bf16"))
    output = tile.read_register(7)
    return [output[row * 16:(row + 1) * 16] for row in range(16)]
