"""Lower concrete 16x16 kernels into Grider ISA programs (v0.2 and v0.3)."""

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
    """Sum documented tile latencies: 2 cycles with no reads, 3 with one
    read, 4 with two reads or GATHER, 5 with three reads (MAC/SEL)."""
    cycles = 0
    for insn in program:
        op = Opcode(int(insn.opcode))
        if op in (Opcode.NOP, Opcode.MOVI):
            # MOVI with a non-inherit dtype has no source reads.
            cycles += 2
        elif op in (Opcode.MAC, Opcode.SEL):
            cycles += 5
        elif op in (Opcode.GATHER,):
            cycles += 4  # one RF read + one SRAM read
        elif op in (
            Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.AND, Opcode.OR,
            Opcode.XOR, Opcode.SHL, Opcode.SHR, Opcode.MIN, Opcode.MAX,
            Opcode.SCATTER, Opcode.DIV, Opcode.DOT_ROW,
        ):
            cycles += 4
        elif op in (Opcode.CONVERT,):
            cycles += 3
        else:
            # Single-read tile ops: MOV, NEIGHBOR, LOAD, STORE, reductions,
            # SCAN, TRANSPOSE, broadcasts.
            cycles += 3
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


def lower_transpose16(a: Matrix) -> tuple[Instruction, ...]:
    """Lower a concrete BF16 16x16 transpose via TRANSPOSE.

    Loads each element with a single-lane MOVI into register 0, then one
    TRANSPOSE writes the transposed matrix to register 3.
    """
    _check_matrix(a, "a")
    program: list[Instruction] = []
    for row in range(16):
        for col in range(16):
            lane = row * 16 + col
            program.append(Instruction(
                Opcode.MOVI, dst=0,
                imm=float_to_bf16(float(a[row][col])), dtype=DataType.BF16,
                lane_mask=1 << lane,
            ))
    program.append(Instruction(
        Opcode.TRANSPOSE, dst=OUTPUT_REGISTER, src_a=0, imm=0,
        dtype=DataType.BF16, lane_mask=ALL_LANES,
    ))
    return tuple(program)


def execute_lowered_transpose16(a: Matrix) -> LoweredGemmResult:
    """Run the transpose lowering and compare with the Python transpose."""
    program = lower_transpose16(a)
    tile = Tile()
    for insn in program:
        tile.step(insn)
    flat = tile.read_register(OUTPUT_REGISTER)
    output = [flat[row * 16:(row + 1) * 16] for row in range(16)]
    reference = [[a[col][row] for col in range(16)] for row in range(16)]
    from .sim import bf16_to_float as _bf
    differences = [
        abs(float(output[row][col]) - float(_bf(float_to_bf16(float(reference[row][col])))))
        for row in range(16) for col in range(16)
    ]
    max_error = math.inf if any(math.isnan(e) for e in differences) else max(differences)
    return LoweredGemmResult(
        output=output,
        reference=[[float(v) for v in row] for row in reference],
        instruction_count=len(program),
        estimated_rtl_cycles=_rtl_cycle_estimate(program),
        max_absolute_error=max_error,
        program=program,
    )


def lower_qk_scores_row16(q_row: Sequence[float],
                          k: Matrix) -> tuple[Instruction, ...]:
    """Lower Q[0,:] x K^T scores (16 scores) using DOT_ROW.

    The query row is replicated into all 16 tile rows in register 0 and the
    K matrix is loaded row-wise in register 1. One DOT_ROW instruction then
    produces score[y] = dot(Q, K[y,:]) in row y (broadcast across the row).
    """
    if len(q_row) != 16:
        raise ValueError("q_row must have 16 elements")
    _check_matrix(k, "k")
    program: list[Instruction] = []
    for row in range(16):
        for col in range(16):
            lane = row * 16 + col
            program.append(Instruction(
                Opcode.MOVI, dst=0,
                imm=float_to_bf16(float(q_row[col])), dtype=DataType.BF16,
                lane_mask=1 << lane,
            ))
    for row in range(16):
        for col in range(16):
            lane = row * 16 + col
            program.append(Instruction(
                Opcode.MOVI, dst=1,
                imm=float_to_bf16(float(k[row][col])), dtype=DataType.BF16,
                lane_mask=1 << lane,
            ))
    program.append(Instruction(
        Opcode.DOT_ROW, dst=OUTPUT_REGISTER, src_a=0, src_b=1,
        dtype=DataType.BF16, lane_mask=ALL_LANES,
    ))
    return tuple(program)


def execute_lowered_qk_scores_row16(q_row: Sequence[float],
                                    k: Matrix) -> LoweredGemmResult:
    """Run the QK lowering and report scores."""
    program = lower_qk_scores_row16(q_row, k)
    tile = Tile()
    for insn in program:
        tile.step(insn)
    flat = tile.read_register(OUTPUT_REGISTER)
    from .sim import _f32_add_bits, _f32_mul_bits, bf16_to_float as _bf, f32_to_float
    ref_bf: list[float] = []
    for row in range(16):
        acc_bits = 0
        for i in range(16):
            a_bits = float_to_bf16(float(q_row[i])) << 16
            b_bits = float_to_bf16(float(k[row][i])) << 16
            acc_bits = _f32_add_bits(acc_bits, _f32_mul_bits(a_bits, b_bits))
        ref_bf.append(_bf(float_to_bf16(f32_to_float(acc_bits))))
    flat_output = [float(flat[row * 16]) for row in range(16)]
    differences = [
        abs(float(flat_output[row]) - float(ref_bf[row])) for row in range(16)
    ]
    max_error = math.inf if any(math.isnan(e) for e in differences) else max(differences)
    return LoweredGemmResult(
        output=[[flat_output[row]] * 16 for row in range(16)],
        reference=[[ref_bf[row]] * 16 for row in range(16)],
        instruction_count=len(program),
        estimated_rtl_cycles=_rtl_cycle_estimate(program),
        max_absolute_error=max_error,
        program=program,
    )
