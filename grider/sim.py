# SPDX-License-Identifier: Apache-2.0

"""Small, dependency-free functional model of a Grider 16x16 tile.

The model treats a typed register as a 128-bit payload plus a four-bit tag.
One Instruction is decoded once by Tile.step and then applied to active lanes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from fractions import Fraction
import math
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
    F32 = 0x8


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
    REDUCE_SUM = 18
    REDUCE_MAX = 19
    CONVERT = 20
    TRANSPOSE = 21
    REDUCE_SUM_COL = 22
    REDUCE_MAX_COL = 23
    SCAN_SUM = 24
    GATHER = 25
    SCATTER = 26
    ROW_BROADCAST = 27
    COL_BROADCAST = 28
    DIV = 29
    DOT_ROW = 30


@dataclass(frozen=True)
class Instruction:
    opcode: Opcode
    dst: int = 0
    src_a: int = 0
    src_b: int = 0
    src_c: int = 0
    imm: int = 0
    dtype: DataType | None = None
    lane_mask: int = (1 << LANES) - 1

    def __post_init__(self) -> None:
        if not isinstance(self.opcode, int) or not 0 <= self.opcode < 32:
            raise ValueError("opcode must fit the 5-bit instruction field")
        if self.dtype is not None and (
            not isinstance(self.dtype, int) or not 0 <= self.dtype < 16
        ):
            raise ValueError("dtype must fit the 4-bit instruction field")
        for name in ("dst", "src_a", "src_b", "src_c"):
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
            DataType.PRED: 1, DataType.U128: 128, DataType.F32: 32}[dtype]


def _signed(value: int, width: int) -> int:
    value &= (1 << width) - 1
    sign = 1 << (width - 1)
    return value - (1 << width) if value & sign else value


def _pack(value: int, dtype: DataType) -> int:
    if dtype == DataType.BF16:
        return value & 0xFFFF
    if dtype == DataType.F32:
        return value & 0xFFFFFFFF
    return value & ((1 << _width(dtype)) - 1)


_NUMERIC_DTYPES = frozenset({
    DataType.I4, DataType.I8, DataType.I16, DataType.I32, DataType.I64,
    DataType.BF16, DataType.F32,
})
_INT_DTYPES = frozenset({
    DataType.I4, DataType.I8, DataType.I16, DataType.I32, DataType.I64,
})
_NUMERIC_OPS = frozenset({
    Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.MAC, Opcode.MIN, Opcode.MAX,
    Opcode.REDUCE_SUM, Opcode.REDUCE_MAX, Opcode.REDUCE_SUM_COL,
    Opcode.REDUCE_MAX_COL, Opcode.SCAN_SUM, Opcode.DOT_ROW,
})
# Ops that ignore their dtype field and preserve operand tags.
_TAG_PRESERVING_OPS = frozenset({
    Opcode.MOV, Opcode.NEIGHBOR, Opcode.LOAD, Opcode.STORE,
    Opcode.TRANSPOSE, Opcode.GATHER, Opcode.SCATTER,
    Opcode.ROW_BROADCAST, Opcode.COL_BROADCAST,
})


def _supports_dtype(op: Opcode, dtype: DataType) -> bool:
    """Return whether the ISA defines this arithmetic/type combination."""
    if op == Opcode.CONVERT:
        return dtype in (DataType.BF16, DataType.F32)
    if op == Opcode.DIV:
        return dtype in _INT_DTYPES
    if op in _TAG_PRESERVING_OPS:
        return True
    if op == Opcode.MAC and dtype == DataType.BF16:
        return True
    return op not in _NUMERIC_OPS or dtype in _NUMERIC_DTYPES


def float_to_bf16(value: float) -> int:
    """Convert IEEE float32 to BF16 using round-to-nearest, ties-to-even."""
    try:
        bits = struct.unpack(">I", struct.pack(">f", float(value)))[0]
    except OverflowError:
        bits = 0xFF800000 if float(value) < 0 else 0x7F800000
    # Keep NaNs as NaNs instead of rounding a quiet-NaN payload to infinity.
    if bits & 0x7F800000 == 0x7F800000 and bits & 0x007FFFFF:
        return 0x7FC0
    upper, lower = bits >> 16, bits & 0xFFFF
    if lower > 0x8000 or (lower == 0x8000 and upper & 1):
        upper += 1
    return upper & 0xFFFF


def bf16_to_float(value: int) -> float:
    return struct.unpack(">f", struct.pack(">I", (value & 0xFFFF) << 16))[0]


def float_to_f32(value: float) -> int:
    """Return the IEEE-754 binary32 bit pattern for value."""
    try:
        return struct.unpack(">I", struct.pack(">f", float(value)))[0]
    except OverflowError:
        return 0xFF800000 if value < 0 else 0x7F800000


def _f32_arithmetic_bits(value: float) -> int:
    """Match the RTL's canonical quiet NaN for arithmetic results."""
    bits = float_to_f32(value)
    if (bits & 0x7F800000) == 0x7F800000 and (bits & 0x007FFFFF):
        return 0x7FC00000
    return bits


_F32_SIGN_BIT = 0x80000000
_F32_INFINITY = 0x7F800000
_F32_QUIET_NAN = 0x7FC00000
_F32_EXPONENT_MASK = 0x7F800000
_F32_FRACTION_MASK = 0x007FFFFF


def _f32_is_nan(bits: int) -> bool:
    return (bits & _F32_EXPONENT_MASK) == _F32_EXPONENT_MASK and (bits & _F32_FRACTION_MASK) != 0


def _f32_is_inf(bits: int) -> bool:
    return (bits & _F32_EXPONENT_MASK) == _F32_EXPONENT_MASK and (bits & _F32_FRACTION_MASK) == 0


def _f32_is_zero(bits: int) -> bool:
    return (bits & 0x7FFFFFFF) == 0


def _f32_exact(bits: int) -> Fraction:
    """Return the exact value of a finite binary32 bit pattern."""
    sign = -1 if bits & _F32_SIGN_BIT else 1
    exponent = (bits >> 23) & 0xFF
    fraction = bits & _F32_FRACTION_MASK
    if exponent == 0:
        return Fraction(sign * fraction, 1 << 149)
    mantissa = (1 << 23) | fraction
    power = exponent - 127 - 23
    if power >= 0:
        return Fraction(sign * mantissa * (1 << power))
    return Fraction(sign * mantissa, 1 << -power)


def _f32_round(value: Fraction) -> int:
    """Round an exact value to binary32 using round-to-nearest, ties-to-even."""
    if value == 0:
        return 0
    negative = value < 0
    magnitude = -value if negative else value
    sign_bit = _F32_SIGN_BIT if negative else 0
    if magnitude >= Fraction(2) ** 128:
        return sign_bit | _F32_INFINITY
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if magnitude < Fraction(2) ** exponent:
        exponent -= 1
    elif magnitude >= Fraction(2) ** (exponent + 1):
        exponent += 1
    if exponent < -126:
        quantum = Fraction(2) ** -149
        significand = magnitude / quantum
        whole = significand.numerator // significand.denominator
        remainder = significand - whole
        if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and (whole & 1)):
            whole += 1
        if whole >= (1 << 23):
            return sign_bit | (1 << 23)
        return sign_bit | whole
    quantum = Fraction(2) ** (exponent - 23)
    significand = magnitude / quantum
    whole = significand.numerator // significand.denominator
    remainder = significand - whole
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and (whole & 1)):
        whole += 1
    if whole >= (1 << 24):
        whole >>= 1
        exponent += 1
        if exponent > 127:
            return sign_bit | _F32_INFINITY
    return sign_bit | ((exponent + 127) << 23) | (whole - (1 << 23))


def _f32_add_bits(a_bits: int, b_bits: int) -> int:
    if _f32_is_nan(a_bits) or _f32_is_nan(b_bits):
        return _F32_QUIET_NAN
    if _f32_is_inf(a_bits) or _f32_is_inf(b_bits):
        if (_f32_is_inf(a_bits) and _f32_is_inf(b_bits)
                and (a_bits & _F32_SIGN_BIT) != (b_bits & _F32_SIGN_BIT)):
            return _F32_QUIET_NAN
        return a_bits if _f32_is_inf(a_bits) else b_bits
    if _f32_is_zero(a_bits) and _f32_is_zero(b_bits):
        return (a_bits & b_bits) & _F32_SIGN_BIT
    return _f32_round(_f32_exact(a_bits) + _f32_exact(b_bits))


def _f32_sub_bits(a_bits: int, b_bits: int) -> int:
    return _f32_add_bits(a_bits, b_bits ^ _F32_SIGN_BIT)


def _f32_mul_bits(a_bits: int, b_bits: int) -> int:
    if _f32_is_nan(a_bits) or _f32_is_nan(b_bits):
        return _F32_QUIET_NAN
    sign_bit = _F32_SIGN_BIT if (a_bits & _F32_SIGN_BIT) != (b_bits & _F32_SIGN_BIT) else 0
    if _f32_is_inf(a_bits) or _f32_is_inf(b_bits):
        if _f32_is_zero(a_bits) or _f32_is_zero(b_bits):
            return _F32_QUIET_NAN
        return sign_bit | _F32_INFINITY
    if _f32_is_zero(a_bits) or _f32_is_zero(b_bits):
        return sign_bit
    return _f32_round(_f32_exact(a_bits) * _f32_exact(b_bits))


def _f32_less_than(a_bits: int, b_bits: int) -> bool:
    a_zero = _f32_is_zero(a_bits)
    b_zero = _f32_is_zero(b_bits)
    if a_zero and b_zero:
        return False
    a_negative = bool(a_bits & _F32_SIGN_BIT)
    b_negative = bool(b_bits & _F32_SIGN_BIT)
    if a_negative != b_negative:
        return a_negative
    magnitude_a = a_bits & 0x7FFFFFFF
    magnitude_b = b_bits & 0x7FFFFFFF
    if a_negative:
        return magnitude_a > magnitude_b
    return magnitude_a < magnitude_b


def _f32_min_bits(a_bits: int, b_bits: int) -> int:
    if _f32_is_nan(a_bits) or _f32_is_nan(b_bits):
        return _F32_QUIET_NAN
    return b_bits if _f32_less_than(b_bits, a_bits) else a_bits


def _f32_max_bits(a_bits: int, b_bits: int) -> int:
    if _f32_is_nan(a_bits) or _f32_is_nan(b_bits):
        return _F32_QUIET_NAN
    return b_bits if _f32_less_than(a_bits, b_bits) else a_bits


_BF16_SIGN_BIT = 0x8000
_BF16_INFINITY = 0x7F80
_BF16_QUIET_NAN = 0x7FC0
_BF16_EXPONENT_MASK = 0x7F80
_BF16_FRACTION_MASK = 0x007F


def _bf16_is_nan(bits: int) -> bool:
    return (bits & _BF16_EXPONENT_MASK) == _BF16_EXPONENT_MASK and (bits & _BF16_FRACTION_MASK) != 0


def _bf16_is_inf(bits: int) -> bool:
    return (bits & _BF16_EXPONENT_MASK) == _BF16_EXPONENT_MASK and (bits & _BF16_FRACTION_MASK) == 0


def _bf16_is_zero(bits: int) -> bool:
    return (bits & 0x7FFF) == 0


def _bf16_exact(bits: int) -> Fraction:
    """Return the exact value of a finite bfloat16 bit pattern."""
    sign = -1 if bits & _BF16_SIGN_BIT else 1
    exponent = (bits >> 7) & 0xFF
    fraction = bits & _BF16_FRACTION_MASK
    if exponent == 0:
        return Fraction(sign * fraction, 1 << 133)
    mantissa = (1 << 7) | fraction
    power = exponent - 127 - 7
    if power >= 0:
        return Fraction(sign * mantissa * (1 << power))
    return Fraction(sign * mantissa, 1 << -power)


def _bf16_round(value: Fraction) -> int:
    """Round an exact value to bfloat16 using round-to-nearest, ties-to-even."""
    if value == 0:
        return 0
    negative = value < 0
    magnitude = -value if negative else value
    sign_bit = _BF16_SIGN_BIT if negative else 0
    if magnitude >= Fraction(2) ** 128:
        return sign_bit | _BF16_INFINITY
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if magnitude < Fraction(2) ** exponent:
        exponent -= 1
    elif magnitude >= Fraction(2) ** (exponent + 1):
        exponent += 1
    if exponent < -126:
        quantum = Fraction(2) ** -133
        significand = magnitude / quantum
        whole = significand.numerator // significand.denominator
        remainder = significand - whole
        if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and (whole & 1)):
            whole += 1
        if whole >= (1 << 7):
            return sign_bit | (1 << 7)
        return sign_bit | whole
    quantum = Fraction(2) ** (exponent - 7)
    significand = magnitude / quantum
    whole = significand.numerator // significand.denominator
    remainder = significand - whole
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and (whole & 1)):
        whole += 1
    if whole >= (1 << 8):
        whole >>= 1
        exponent += 1
        if exponent > 127:
            return sign_bit | _BF16_INFINITY
    return sign_bit | ((exponent + 127) << 7) | (whole - (1 << 7))


def _bf16_add_bits(a_bits: int, b_bits: int) -> int:
    if _bf16_is_nan(a_bits) or _bf16_is_nan(b_bits):
        return _BF16_QUIET_NAN
    if _bf16_is_inf(a_bits) or _bf16_is_inf(b_bits):
        if (_bf16_is_inf(a_bits) and _bf16_is_inf(b_bits)
                and (a_bits & _BF16_SIGN_BIT) != (b_bits & _BF16_SIGN_BIT)):
            return _BF16_QUIET_NAN
        return a_bits if _bf16_is_inf(a_bits) else b_bits
    if _bf16_is_zero(a_bits) and _bf16_is_zero(b_bits):
        return (a_bits & b_bits) & _BF16_SIGN_BIT
    return _bf16_round(_bf16_exact(a_bits) + _bf16_exact(b_bits))


def f32_to_float(value: int) -> float:
    return struct.unpack(">f", struct.pack(">I", value & 0xFFFFFFFF))[0]


def _decode(reg: _Register, dtype: DataType | None = None) -> int | float:
    kind = dtype if dtype is not None else reg.dtype
    if kind == DataType.BF16:
        return bf16_to_float(reg.payload)
    if kind == DataType.F32:
        return f32_to_float(reg.payload)
    if kind == DataType.U128:
        return reg.payload & MASK128
    if kind == DataType.PRED:
        return reg.payload & 1
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
            payload = (float_to_bf16(value) if dtype == DataType.BF16 else
                       float_to_f32(value) if dtype == DataType.F32 else _pack(int(value), dtype))
            self._rf[lane][register] = _Register(payload, dtype)

    def read_register(self, register: int, *, decoded: bool = True) -> list[int | float]:
        if not 0 <= register < REGISTERS:
            raise ValueError("register index out of range")
        if decoded:
            return [_decode(self._rf[lane][register]) for lane in range(LANES)]
        return [self._rf[lane][register].payload for lane in range(LANES)]

    def read_register_raw(self, register: int) -> list[tuple[int, DataType]]:
        """Return payload/tag pairs in lane order for RTL comparison tools."""
        if not 0 <= register < REGISTERS:
            raise ValueError("register index out of range")
        return [(self._rf[lane][register].payload, self._rf[lane][register].dtype)
                for lane in range(LANES)]

    def read_sram_raw(self, address: int) -> list[tuple[int, DataType]]:
        if not 0 <= address < LOCAL_WORDS:
            raise ValueError("local SRAM address out of range")
        return [(self._sram[lane][address].payload, self._sram[lane][address].dtype)
                for lane in range(LANES)]

    def load_sram(self, address: int, values: Sequence[int | float], dtype: DataType) -> None:
        if not 0 <= address < LOCAL_WORDS or len(values) != LANES:
            raise ValueError("expected a valid SRAM word and exactly 256 values")
        for lane, value in enumerate(values):
            payload = (float_to_bf16(value) if dtype == DataType.BF16 else
                       float_to_f32(value) if dtype == DataType.F32 else _pack(int(value), dtype))
            self._sram[lane][address] = _Register(payload, dtype)

    def read_sram(self, address: int, lane: int, *, decoded: bool = True) -> int | float:
        reg = self._sram[lane][address]
        return _decode(reg) if decoded else reg.payload

    def step(self, insn: Instruction, *, neighbor_resolver=None) -> None:
        """Issue one instruction; reserved encodings complete as no-ops."""
        try:
            op = Opcode(int(insn.opcode))
        except (TypeError, ValueError):
            self.cycles += 1
            return

        raw_dtype = insn.dtype
        if raw_dtype is None:
            dtype = None
        else:
            try:
                dtype_value = int(raw_dtype)
            except (TypeError, ValueError):
                self.cycles += 1
                return
            if dtype_value == 0xF:
                dtype = None
            else:
                try:
                    dtype = DataType(dtype_value)
                except ValueError:
                    self.cycles += 1
                    return

        immediate = int(insn.imm) & MASK128
        address = immediate & (LOCAL_WORDS - 1)
        direction = immediate & 0x7

        if op in (Opcode.REDUCE_SUM, Opcode.REDUCE_MAX,
                  Opcode.REDUCE_SUM_COL, Opcode.REDUCE_MAX_COL):
            is_col = op in (Opcode.REDUCE_SUM_COL, Opcode.REDUCE_MAX_COL)
            is_sum = op in (Opcode.REDUCE_SUM, Opcode.REDUCE_SUM_COL)
            groups = 16
            for group in range(groups):
                if is_col:
                    lanes = [row * self.width + group for row in range(self.height)]
                else:
                    lanes = [group * self.width + col for col in range(self.width)]
                active = [lane for lane in lanes if (insn.lane_mask >> lane) & 1]
                if not active:
                    continue
                out_type = dtype if dtype is not None else self._rf[active[0]][insn.src_a].dtype
                if not _supports_dtype(op, out_type):
                    continue
                group_values = [self._rf[lane][insn.src_a] for lane in active]
                has_nan = out_type in (DataType.BF16, DataType.F32) and any(
                    math.isnan(_decode(value, out_type)) for value in group_values
                )
                if has_nan:
                    nan_payload = 0x7FC0 if out_type == DataType.BF16 else 0x7FC00000
                    result = _Register(nan_payload, out_type)
                else:
                    partial: list[_Register | None] = [
                        self._rf[lane][insn.src_a] if (insn.lane_mask >> lane) & 1 else None
                        for lane in lanes
                    ]
                    stride = 1
                    while stride < len(lanes):
                        for start in range(0, len(lanes), stride * 2):
                            if start + stride >= len(lanes):
                                break
                            left = partial[start]
                            right = partial[start + stride]
                            if left is None:
                                partial[start] = right
                            elif right is not None:
                                if out_type == DataType.F32:
                                    left_bits = left.payload & 0xFFFFFFFF
                                    right_bits = right.payload & 0xFFFFFFFF
                                    if is_sum:
                                        payload = _f32_add_bits(left_bits, right_bits)
                                    else:
                                        payload = _f32_max_bits(left_bits, right_bits)
                                else:
                                    left_value = _decode(left, out_type)
                                    right_value = _decode(right, out_type)
                                    value = left_value + right_value if is_sum else max(left_value, right_value)
                                    if out_type == DataType.BF16:
                                        payload = float_to_bf16(float(value))
                                    else:
                                        payload = _pack(int(value), out_type)
                                partial[start] = _Register(payload, out_type)
                        stride *= 2
                    result = partial[0]
                assert result is not None
                for lane in active:
                    self._rf[lane][insn.dst] = _Register(result.payload, result.dtype)
            self.cycles += 1
            return

        if op == Opcode.SCAN_SUM:
            for row in range(self.height):
                lanes = [row * self.width + col for col in range(self.width)]
                active = [lane for lane in lanes if (insn.lane_mask >> lane) & 1]
                if not active:
                    continue
                out_type = dtype if dtype is not None else self._rf[active[0]][insn.src_a].dtype
                if not _supports_dtype(op, out_type):
                    continue
                prefix: list[int] = []
                for lane in lanes:
                    if (insn.lane_mask >> lane) & 1:
                        if out_type == DataType.F32:
                            prefix.append(self._rf[lane][insn.src_a].payload & 0xFFFFFFFF)
                        elif out_type == DataType.BF16:
                            prefix.append(self._rf[lane][insn.src_a].payload & 0xFFFF)
                        else:
                            prefix.append(_pack(int(_decode(self._rf[lane][insn.src_a], out_type)), out_type))
                    else:
                        prefix.append(0)
                stride = 1
                while stride < self.width:
                    for col in range(self.width - 1, stride - 1, -1):
                        if out_type == DataType.F32:
                            prefix[col] = _f32_add_bits(prefix[col], prefix[col - stride])
                        elif out_type == DataType.BF16:
                            prefix[col] = _bf16_add_bits(prefix[col], prefix[col - stride])
                        else:
                            prefix[col] = _pack(int(prefix[col]) + int(prefix[col - stride]), out_type)
                    stride *= 2
                for col in range(self.width):
                    if (insn.lane_mask >> lanes[col]) & 1:
                        self._rf[lanes[col]][insn.dst] = _Register(prefix[col], out_type)
            self.cycles += 1
            return

        if op == Opcode.DOT_ROW:
            for row in range(self.height):
                lanes = [row * self.width + col for col in range(self.width)]
                active = [lane for lane in lanes if (insn.lane_mask >> lane) & 1]
                if not active:
                    continue
                out_type = dtype if dtype is not None else self._rf[active[0]][insn.src_a].dtype
                if not _supports_dtype(op, out_type):
                    continue
                products: list[int] = []
                valid: list[bool] = []
                for lane in lanes:
                    if (insn.lane_mask >> lane) & 1:
                        if out_type == DataType.F32:
                            a_bits = self._rf[lane][insn.src_a].payload & 0xFFFFFFFF
                            b_bits = self._rf[lane][insn.src_b].payload & 0xFFFFFFFF
                            products.append(_f32_mul_bits(a_bits, b_bits))
                        elif out_type == DataType.BF16:
                            a_bits = (self._rf[lane][insn.src_a].payload & 0xFFFF) << 16
                            b_bits = (self._rf[lane][insn.src_b].payload & 0xFFFF) << 16
                            products.append(_f32_mul_bits(a_bits, b_bits))
                        else:
                            av = int(_decode(self._rf[lane][insn.src_a], out_type))
                            bv = int(_decode(self._rf[lane][insn.src_b], out_type))
                            products.append(av * bv)
                        valid.append(True)
                    else:
                        products.append(0)
                        valid.append(False)
                stride = 1
                while stride < self.width:
                    for start in range(0, self.width, stride * 2):
                        if start + stride < self.width:
                            if valid[start] and valid[start + stride]:
                                if out_type in (DataType.BF16, DataType.F32):
                                    products[start] = _f32_add_bits(products[start], products[start + stride])
                                else:
                                    products[start] = products[start] + products[start + stride]
                            elif not valid[start] and valid[start + stride]:
                                products[start] = products[start + stride]
                                valid[start] = True
                    stride *= 2
                if not valid[0]:
                    continue
                if out_type == DataType.BF16:
                    result = _Register(float_to_bf16(f32_to_float(products[0])), DataType.BF16)
                elif out_type == DataType.F32:
                    result = _Register(products[0], DataType.F32)
                else:
                    result = _Register(_pack(int(products[0]), out_type), out_type)
                for lane in active:
                    self._rf[lane][insn.dst] = _Register(result.payload, result.dtype)
            self.cycles += 1
            return

        # Stage register writes before commit so in-place neighbor operations
        # read the pre-instruction state.
        writes: list[tuple[int, _Register]] = []
        for lane in range(LANES):
            if not ((insn.lane_mask >> lane) & 1):
                continue

            a = self._rf[lane][insn.src_a]
            b = self._rf[lane][insn.src_b]
            c = self._rf[lane][insn.src_c]
            out_type = dtype if dtype is not None else (b.dtype if op == Opcode.SEL else a.dtype)

            if op == Opcode.NOP:
                continue
            if op == Opcode.STORE:
                self._sram[lane][address] = _Register(a.payload, a.dtype)
                continue
            if op == Opcode.LOAD:
                reg = self._sram[lane][address]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.NEIGHBOR:
                neighbor = self._neighbor_lane(lane, direction)
                if neighbor is None and neighbor_resolver is not None:
                    reg = neighbor_resolver(lane, direction, insn.src_a)
                else:
                    reg = _Register(0, a.dtype) if neighbor is None else self._rf[neighbor][insn.src_a]
                if reg is None:
                    reg = _Register(0, a.dtype)
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.TRANSPOSE:
                src_lane = self._permute_lane(lane, direction)
                reg = self._rf[src_lane][insn.src_a]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.ROW_BROADCAST:
                src_lane = (lane // 16) * 16
                reg = self._rf[src_lane][insn.src_a]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.COL_BROADCAST:
                src_lane = lane % 16
                reg = self._rf[src_lane][insn.src_a]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.GATHER:
                slot = a.payload & (LOCAL_WORDS - 1)
                reg = self._sram[lane][slot]
                writes.append((lane, _Register(reg.payload, reg.dtype)))
                continue
            if op == Opcode.SCATTER:
                slot = b.payload & (LOCAL_WORDS - 1)
                self._sram[lane][slot] = _Register(a.payload, a.dtype)
                continue
            if not _supports_dtype(op, out_type):
                continue

            if op == Opcode.MOV:
                # MOV preserves the source tag; its dtype field is ignored.
                payload = _pack(a.payload, a.dtype)
                writes.append((lane, _Register(payload, a.dtype)))
                continue
            if op == Opcode.MOVI:
                payload = _pack(immediate, out_type)
                writes.append((lane, _Register(payload, out_type)))
                continue
            if op == Opcode.CONVERT:
                if not ((a.dtype == DataType.F32 and out_type == DataType.BF16) or
                        (a.dtype == DataType.BF16 and out_type == DataType.F32)):
                    continue
                value = _decode(a)
                if out_type == DataType.BF16:
                    payload = float_to_bf16(float(value))
                elif out_type == DataType.F32:
                    payload = float_to_f32(float(value))
                else:
                    continue
                writes.append((lane, _Register(payload, out_type)))
                continue
            if op == Opcode.SEL:
                selected = b if a.payload != 0 else c
                payload = _pack(selected.payload, out_type)
                writes.append((lane, _Register(payload, out_type)))
                continue

            # Arithmetic inherits one common operand type. SEL is handled
            # above because its inherited result type comes from src_b.
            if out_type == DataType.F32:
                a_bits = a.payload & 0xFFFFFFFF
                b_bits = b.payload & 0xFFFFFFFF
                if op == Opcode.ADD:
                    result_bits = _f32_add_bits(a_bits, b_bits)
                elif op == Opcode.SUB:
                    result_bits = _f32_sub_bits(a_bits, b_bits)
                elif op == Opcode.MUL:
                    result_bits = _f32_mul_bits(a_bits, b_bits)
                elif op == Opcode.MAC:
                    acc_bits = self._rf[lane][insn.dst].payload & 0xFFFFFFFF
                    result_bits = _f32_add_bits(acc_bits, _f32_mul_bits(a_bits, b_bits))
                elif op == Opcode.MIN:
                    result_bits = _f32_min_bits(a_bits, b_bits)
                elif op == Opcode.MAX:
                    result_bits = _f32_max_bits(a_bits, b_bits)
                else:
                    continue
                writes.append((lane, _Register(result_bits, DataType.F32)))
                continue

            if out_type == DataType.BF16 and op == Opcode.MAC:
                accumulator = self._rf[lane][insn.dst]
                acc_bits = (accumulator.payload & 0xFFFFFFFF if accumulator.dtype == DataType.F32
                            else (accumulator.payload & 0xFFFF) << 16)
                a_bits = (a.payload & 0xFFFF) << 16
                b_bits = (b.payload & 0xFFFF) << 16
                result_bits = _f32_add_bits(acc_bits, _f32_mul_bits(a_bits, b_bits))
                writes.append((lane, _Register(result_bits, DataType.F32)))
                continue

            av = _decode(a, out_type)
            bv = _decode(b, out_type)
            if op == Opcode.ADD:
                result = av + bv
            elif op == Opcode.SUB:
                result = av - bv
            elif op == Opcode.MUL:
                result = av * bv
            elif op == Opcode.DIV:
                # Truncating integer division; division by zero yields 0.
                if int(bv) == 0:
                    result = 0
                else:
                    result = abs(int(av)) // abs(int(bv))
                    if (int(av) < 0) != (int(bv) < 0):
                        result = -result
            elif op == Opcode.MAC:
                accumulator = self._rf[lane][insn.dst]
                old = _decode(accumulator, out_type)
                result = old + av * bv
            elif op == Opcode.AND:
                result = a.payload & b.payload
            elif op == Opcode.OR:
                result = a.payload | b.payload
            elif op == Opcode.XOR:
                result = a.payload ^ b.payload
            elif op == Opcode.SHL:
                result = a.payload << (b.payload & 0x7F)
            elif op == Opcode.SHR:
                shift = b.payload & 0x7F
                if out_type in (DataType.I4, DataType.I8, DataType.I16,
                                DataType.I32, DataType.I64):
                    result = int(av) >> shift
                else:
                    result = a.payload >> shift
            elif op == Opcode.MIN:
                result = math.nan if out_type == DataType.BF16 and (math.isnan(av) or math.isnan(bv)) else min(av, bv)
            elif op == Opcode.MAX:
                result = math.nan if out_type == DataType.BF16 and (math.isnan(av) or math.isnan(bv)) else max(av, bv)
            else:
                # Unknown v0 opcodes are defined as no-ops above.
                continue

            payload = (float_to_bf16(float(result)) if out_type == DataType.BF16 else
                       _pack(int(result), out_type))
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

    @staticmethod
    def _permute_lane(lane: int, kind: int) -> int:
        x, y = lane % 16, lane // 16
        kind &= 0x7
        if kind == 0:  # transpose: (x,y) -> (y,x)
            sx, sy = y, x
        elif kind == 1:  # flip X
            sx, sy = 15 - x, y
        elif kind == 2:  # flip Y
            sx, sy = x, 15 - y
        elif kind == 3:  # rotate 90 CW: dest(x,y) <- src(y,15-x)
            sx, sy = y, 15 - x
        elif kind == 4:  # rotate 90 CCW: dest(x,y) <- src(15-y,x)
            sx, sy = 15 - y, x
        elif kind == 5:  # anti-transpose
            sx, sy = 15 - y, 15 - x
        elif kind == 6:  # rotate 180
            sx, sy = 15 - x, 15 - y
        else:  # identity
            sx, sy = x, y
        return sy * 16 + sx


class Mesh:
    """Rectangular mesh of SIMD tiles with synchronous inter-tile halos."""

    def __init__(self, tiles_x: int = 2, tiles_y: int = 2) -> None:
        if tiles_x < 1 or tiles_y < 1:
            raise ValueError("mesh dimensions must both be positive")
        self.tiles_x = tiles_x
        self.tiles_y = tiles_y
        self.tiles = [[Tile() for _ in range(tiles_x)] for _ in range(tiles_y)]
        self.cycles = 0

    def tile_at(self, x: int, y: int) -> Tile:
        if not (0 <= x < self.tiles_x and 0 <= y < self.tiles_y):
            raise ValueError("tile coordinates are outside this mesh")
        return self.tiles[y][x]

    def step(self, insn: Instruction) -> None:
        if insn.opcode != Opcode.NEIGHBOR:
            for row in self.tiles:
                for tile in row:
                    tile.step(insn)
            self.cycles += 1
            return

        # A neighbor instruction observes one mesh-wide pre-instruction snapshot.
        snapshot = [[[[tile._rf[lane][register] for register in range(REGISTERS)]
                      for lane in range(LANES)] for tile in row] for row in self.tiles]
        directions = ((0, -1), (1, -1), (1, 0), (1, 1),
                      (0, 1), (-1, 1), (-1, 0), (-1, -1))

        for ty in range(self.tiles_y):
            for tx in range(self.tiles_x):
                def resolve(lane: int, direction: int, register: int,
                            tile_x: int = tx, tile_y: int = ty):
                    x, y = lane % 16, lane // 16
                    dx, dy = directions[direction & 0x7]
                    gx, gy = tile_x * 16 + x + dx, tile_y * 16 + y + dy
                    if not (0 <= gx < self.tiles_x * 16 and 0 <= gy < self.tiles_y * 16):
                        return None
                    target_tx, target_x = divmod(gx, 16)
                    target_ty, target_y = divmod(gy, 16)
                    target_lane = target_y * 16 + target_x
                    return snapshot[target_ty][target_tx][target_lane][register]

                self.tiles[ty][tx].step(insn, neighbor_resolver=resolve)
        self.cycles += 1

    def run(self, program: Iterable[Instruction]) -> int:
        for insn in program:
            self.step(insn)
        return self.cycles


def gemm16(a: Sequence[Sequence[int | float]], b: Sequence[Sequence[int | float]],
           dtype: DataType = DataType.I8) -> list[list[int | float]]:
    """Reference 16×16 GEMM for a tile's 256 output cells.

    INT4/INT8 accumulate into signed INT32 results. BF16 inputs accumulate in
    IEEE binary32 and are rounded to BF16 once at output.
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
            acc_bits = 0
            for k in range(16):
                if dtype == DataType.BF16:
                    a_bits = float_to_bf16(float(a[row][k])) << 16
                    b_bits = float_to_bf16(float(b[k][col])) << 16
                    acc_bits = _f32_add_bits(acc_bits, _f32_mul_bits(a_bits, b_bits))
                else:
                    width = _width(dtype)
                    av = _signed(int(a[row][k]), width)
                    bv = _signed(int(b[k][col]), width)
                    acc_bits += av * bv
            if dtype == DataType.BF16:
                output_row.append(bf16_to_float(float_to_bf16(f32_to_float(acc_bits))))
            else:
                output_row.append(_signed(int(acc_bits), 32))
        result.append(output_row)
    return result

