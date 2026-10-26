"""Small, dependency-free functional model of a Grider 16x16 tile.

The model treats a typed register as a 128-bit payload plus a four-bit tag.
One Instruction is decoded once by Tile.step and then applied to active lanes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Iterable, Sequence


LANES = 16 * 16
REGISTERS = 16
LOCAL_WORDS = 16
MASK128 = (1 << 128) - 1


class DataType(IntEnum):
    I4 = 0x0
    I8 = 0x1
    BF16 = 0x2
    I16 = 0x3
    I32 = 0x4
    I64 = 0x5
    U128 = 0x6
    PRED = 0x7


class Opcode(IntEnum):
    NOP = 0
    MOV = 1
    MOVI = 2
    ADD = 3
    SUB = 4
    MUL = 5
    MAC = 6
    AND = 7
    OR = 8
    XOR = 9
    SHL = 10
    SHR = 11
    MIN = 12
    MAX = 13
    SEL = 14
    NEIGHBOR = 15
    LOAD = 16
    STORE = 17


@dataclass(frozen=True)
class Instruction:
    opcode: Opcode
    dst: int = 0
    src_a: int = 0
    src_b: int = 0
    imm: int = 0
    dtype: DataType | None = None
    lane_mask: int = (1 << LANES) - 1

    def __post_init__(self) -> None:
        for name in ("dst", "src_a", "src_b"):
            value = getattr(self, name)
            if not 0 <= value < REGISTERS:
                raise ValueError(f"{name} must be in [0, {REGISTERS})")
        if self.lane_mask < 0 or self.lane_mask >= (1 << LANES):
            raise ValueError(f"lane_mask must be a {LANES}-bit nonnegative value")


@dataclass
class _Register:
    payload: int = 0
    dtype: DataType = DataType.I32


def _width(dtype: DataType) -> int:
    return {DataType.I4: 4, DataType.I8: 8, DataType.I16: 16,
            DataType.I32: 32, DataType.I64: 64, DataType.BF16: 16,
            DataType.PRED: 1, DataType.U128: 128}[dtype]


def _signed(value: int, width: int) -> int:
    value &= (1 << width) - 1
    sign = 1 << (width - 1)
    return value - (1 << width) if value & sign else value


def _pack(value: int, dtype: DataType) -> int:
    if dtype == DataType.BF16:
        return value & 0xFFFF
    return value & ((1 << _width(dtype)) - 1)


def float_to_bf16(value: float) -> int:
    """Convert IEEE float32 to BF16 using round-to-nearest, ties-to-even."""
    bits = struct.unpack(">I", struct.pack(">f", float(value)))[0]
    # Keep NaNs as NaNs instead of rounding a quiet-NaN payload to infinity.
    if bits & 0x7F800000 == 0x7F800000 and bits & 0x007FFFFF:
        return ((bits >> 16) | 0x0040) & 0xFFFF
    upper, lower = bits >> 16, bits & 0xFFFF
    if lower > 0x8000 or (lower == 0x8000 and upper & 1):
        upper += 1
    return upper & 0xFFFF


def bf16_to_float(value: int) -> float:
    return struct.unpack(">f", struct.pack(">I", (value & 0xFFFF) << 16))[0]


def _decode(reg: _Register, dtype: DataType | None = None) -> int | float:
    kind = dtype if dtype is not None else reg.dtype
    if kind == DataType.BF16:
        return bf16_to_float(reg.payload)
    if kind == DataType.U128:
        return reg.payload & MASK128
    return _signed(reg.payload, _width(kind))


class Tile:
    """Functional model of one 16×16 SIMD tile.

    Cell index is row-major (y * 16 + x). Each cell owns its register file and
    local SRAM. `step` is atomic across active lanes, so neighbor instructions
    always observe the pre-instruction tile state.
    """

    width = 16
    height = 16
    lane_count = LANES

    def __init__(self) -> None:
        self._rf = [[_Register() for _ in range(REGISTERS)] for _ in range(LANES)]
        self._sram = [[_Register() for _ in range(LOCAL_WORDS)] for _ in range(LANES)]
        self.cycles = 0

    @staticmethod
    def lane(x: int, y: int) -> int:
        if not (0 <= x < 16 and 0 <= y < 16):
            raise ValueError("cell coordinates must be inside the 16×16 tile")
        return y * 16 + x

    def load_register(self, register: int, values: Sequence[int | float],
                      dtype: DataType) -> None:
        """Host-side initialization helper; values must have one entry per cell."""
        if not 0 <= register < REGISTERS or len(values) != LANES:
            raise ValueError("expected a valid register and exactly 256 values")
        for lane, value in enumerate(values):
            payload = float_to_bf16(value) if dtype == DataType.BF16 else _pack(int(value), dtype)
            self._rf[lane][register] = _Register(payload, dtype)

    def read_register(self, register: int, *, decoded: bool = True) -> list[int | float]:
        if not 0 <= register < REGISTERS:
            raise ValueError("register index out of range")
        if decoded:
            return [_decode(self._rf[lane][register]) for lane in range(LANES)]
        return [self._rf[lane][register].payload for lane in range(LANES)]

    def load_sram(self, address: int, values: Sequence[int | float], dtype: DataType) -> None:
        if not 0 <= address < LOCAL_WORDS or len(values) != LANES:
            raise ValueError("expected a valid SRAM word and exactly 256 values")
        for lane, value in enumerate(values):
            payload = float_to_bf16(value) if dtype == DataType.BF16 else _pack(int(value), dtype)
            self._sram[lane][address] = _Register(payload, dtype)

    def read_sram(self, address: int, lane: int, *, decoded: bool = True) -> int | float:
        reg = self._sram[lane][address]
        return _decode(reg) if decoded else reg.payload

    def step(self, insn: Instruction) -> None:
        """Issue one tile-wide instruction; masked lanes retain their state."""
        op = insn.opcode
        dtype = insn.dtype
        if op == Opcode.NEIGHBOR and not 0 <= insn.imm < 8:
            raise ValueError("NEIGHBOR imm encodes one of 8 directions (0..7)")
        if op in (Opcode.LOAD, Opcode.STORE) and not 0 <= insn.imm < LOCAL_WORDS:
            raise ValueError("local SRAM address must be in [0, 16)")

        # Stage all writes before committing, preserving SIMD and neighborhood semantics.
        writes: list[tuple[int, _Register]] = []
        for lane in range(LANES):
            if not ((insn.lane_mask >> lane) & 1):
                continue
            a = self._rf[lane][insn.src_a]
            b = self._rf[lane][insn.src_b]
            out_type = dtype if dtype is not None else a.dtype
            if op == Opcode.NOP:
                continue
            if op == Opcode.STORE:
                self._sram[lane][insn.imm] = _Register(a.payload, a.dtype)
                continue
            if op == Opcode.LOAD:
                reg = self._sram[lane][insn.imm]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.NEIGHBOR:
                neighbor = self._neighbor_lane(lane, insn.imm)
                reg = _Register(0, out_type) if neighbor is None else self._rf[neighbor][insn.src_a]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue

            av = _decode(a, dtype)
            bv = _decode(b, dtype)
            if op == Opcode.MOV:
                result = av
            elif op == Opcode.MOVI:
                result = insn.imm
            elif op == Opcode.ADD:
                result = av + bv
            elif op == Opcode.SUB:
                result = av - bv
            elif op == Opcode.MUL:
                result = av * bv
            elif op == Opcode.MAC:
                old = _decode(self._rf[lane][insn.dst], dtype)
                result = old + av * bv
            elif op == Opcode.AND:
                result = int(a.payload) & int(b.payload)
            elif op == Opcode.OR:
                result = int(a.payload) | int(b.payload)
            elif op == Opcode.XOR:
                result = int(a.payload) ^ int(b.payload)
            elif op == Opcode.SHL:
                result = int(a.payload) << (int(bv) & 127)
            elif op == Opcode.SHR:
                result = int(av) >> (int(bv) & 127)
            elif op == Opcode.MIN:
                result = min(av, bv)
            elif op == Opcode.MAX:
                result = max(av, bv)
            elif op == Opcode.SEL:
                result = av if a.payload else bv
            else:
                raise ValueError(f"unsupported opcode: {op}")
            payload = float_to_bf16(float(result)) if out_type == DataType.BF16 else _pack(int(result), out_type)
            writes.append((lane, _Register(payload, out_type)))

        for lane, value in writes:
            self._rf[lane][insn.dst] = value
        self.cycles += 1

    @staticmethod
    def _neighbor_lane(lane: int, direction: int) -> int | None:
        # Direction encoding: N, NE, E, SE, S, SW, W, NW.
        dxdy = ((0, -1), (1, -1), (1, 0), (1, 1),
                (0, 1), (-1, 1), (-1, 0), (-1, -1))
        x, y = lane % 16, lane // 16
        dx, dy = dxdy[direction]
        nx, ny = x + dx, y + dy
        return ny * 16 + nx if 0 <= nx < 16 and 0 <= ny < 16 else None

    def run(self, program: Iterable[Instruction]) -> int:
        for insn in program:
            self.step(insn)
        return self.cycles


def gemm16(a: Sequence[Sequence[int | float]], b: Sequence[Sequence[int | float]],
           dtype: DataType = DataType.I8) -> list[list[int | float]]:
    """Reference 16×16 GEMM for a tile's 256 output cells.

    INT4/INT8 accumulate into signed INT32 results. BF16 inputs accumulate in
    Python float and are rounded to BF16 after each product sum (one final round).
    This is a functional reference, not a cycle-accurate microkernel.
    """
    if len(a) != 16 or len(b) != 16 or any(len(row) != 16 for row in a) or any(len(row) != 16 for row in b):
        raise ValueError("gemm16 requires two 16×16 matrices")
    if dtype not in (DataType.I4, DataType.I8, DataType.BF16):
        raise ValueError("gemm16 supports I4, I8, or BF16 inputs")
    result: list[list[int | float]] = []
    for row in range(16):
        output_row: list[int | float] = []
        for col in range(16):
            acc: int | float = 0.0 if dtype == DataType.BF16 else 0
            for k in range(16):
                if dtype == DataType.BF16:
                    av = bf16_to_float(float_to_bf16(float(a[row][k])))
                    bv = bf16_to_float(float_to_bf16(float(b[k][col])))
                else:
                    width = _width(dtype)
                    av = _signed(int(a[row][k]), width)
                    bv = _signed(int(b[k][col]), width)
                acc += av * bv
            output_row.append(bf16_to_float(float_to_bf16(float(acc))) if dtype == DataType.BF16 else _signed(int(acc), 32))
        result.append(output_row)
    return result
