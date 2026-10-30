"""Lower a concrete 16x16 BF16 GEMM into the existing Grider v0.2 ISA."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .sim import DataType, Instruction, Opcode, Tile, float_to_bf16, gemm16


Matrix = Sequence[Sequence[int | float]]
ALL_LANES = (1 << 256) - 1
ACCUMULATOR_REGISTER = 2
OUTPUT_REGISTER = 3


@dataclass(frozen=True)
class LoweredGemmResult:
    output: list[list[int | float]]
    reference: list[list[int | float]]
    instruction_count: int
    estimated_rtl_cycles: int
    max_absolute_error: float
    program: tuple[Instruction, ...]


def _check_matrix(matrix: Matrix, name: str) -> None:
    if len(matrix) != 16 or any(len(row) != 16 for row in matrix):
        raise ValueError(f"{name} must be a 16x16 matrix")


def lower_gemm16(a: Matrix, b: Matrix) -> tuple[Instruction, ...]:
    """Compile concrete BF16 matrices into lane-masked MOVI/MAC instructions.

    Each lane computes one output element. For each reduction index, one MOVI
    per output row broadcasts A[r,k] across that row and one MOVI per output
    column broadcasts B[k,c] down that column; one SIMD MAC then updates all
    256 accumulators. Inputs are embedded as BF16 immediates, so this is a
    compiler correctness path rather than a reusable memory-loading kernel.
    """
    _check_matrix(a, "a")
    _check_matrix(b, "b")
    program: list[Instruction] = [
        Instruction(Opcode.MOVI, dst=ACCUMULATOR_REGISTER, imm=0,
                    dtype=DataType.BF16, lane_mask=ALL_LANES)
    ]
    for k in range(16):
        for row in range(16):
            row_mask = ((1 << 16) - 1) << (row * 16)
            program.append(Instruction(
                Opcode.MOVI, dst=0,
                imm=float_to_bf16(float(a[row][k])), dtype=DataType.BF16,
                lane_mask=row_mask,
            ))
        for col in range(16):
            col_mask = sum(1 << (row * 16 + col) for row in range(16))
            program.append(Instruction(
                Opcode.MOVI, dst=1,
                imm=float_to_bf16(float(b[k][col])), dtype=DataType.BF16,
                lane_mask=col_mask,
            ))
        program.append(Instruction(
            Opcode.MAC, dst=ACCUMULATOR_REGISTER, src_a=0, src_b=1,
            dtype=DataType.BF16, lane_mask=ALL_LANES,
        ))
    program.append(Instruction(
        Opcode.CONVERT, dst=OUTPUT_REGISTER, src_a=ACCUMULATOR_REGISTER,
        dtype=DataType.BF16, lane_mask=ALL_LANES,
    ))
    return tuple(program)


def _rtl_cycle_estimate(program: Sequence[Instruction]) -> int:
    """Sum the documented current-tile instruction latency by source reads."""
    cycles = 0
    for insn in program:
        op = Opcode(int(insn.opcode))
        if op == Opcode.MOVI:
            cycles += 2
        elif op == Opcode.MAC:
            cycles += 5
        elif op == Opcode.CONVERT:
            cycles += 3
        else:
            raise ValueError(f"unsupported instruction in GEMM estimate: {op.name}")
    return cycles


def execute_lowered_gemm16(a: Matrix, b: Matrix) -> LoweredGemmResult:
    """Run the lowered program in the Python tile and report reference error."""
    program = lower_gemm16(a, b)
    tile = Tile()
    for insn in program:
        tile.step(insn)
    flat = tile.read_register(OUTPUT_REGISTER)
    output = [flat[row * 16:(row + 1) * 16] for row in range(16)]
    reference = gemm16(a, b, DataType.BF16)
    differences = [
        abs(float(output[row][col]) - float(reference[row][col]))
        for row in range(16) for col in range(16)
    ]
    max_error = math.inf if any(math.isnan(error) for error in differences) else max(differences)
    return LoweredGemmResult(
        output=output,
        reference=reference,
        instruction_count=len(program),
        estimated_rtl_cycles=_rtl_cycle_estimate(program),
        max_absolute_error=max_error,
        program=program,
    )
