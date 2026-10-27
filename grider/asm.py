"""Assembler for the host-submitted Grider v0.1 instruction stream.

This is a small, straight-line assembly language for the current ISA. It
expands compile-time .repeat blocks; hardware still receives one instruction
at a time through its existing host interface.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .sim import DataType, Instruction, Opcode, float_to_bf16

LANES = 16 * 16
FULL_MASK = (1 << LANES) - 1
MAX_REPEAT = 4096
MAX_INSTRUCTIONS = 100_000

_DTYPE_NAMES = {
    "i4": DataType.I4,
    "i8": DataType.I8,
    "bf16": DataType.BF16,
    "i16": DataType.I16,
    "i32": DataType.I32,
    "i64": DataType.I64,
    "u128": DataType.U128,
    "pred": DataType.PRED,
}
_OPCODE_NAMES = {op.name.lower(): op for op in Opcode}
_DIRECTIONS = {"n": 0, "ne": 1, "e": 2, "se": 3, "s": 4, "sw": 5, "w": 6, "nw": 7}
_REGISTER_RE = re.compile(r"^[rR](\d+)$")
_REPEAT_RE = re.compile(r"^\.repeat\s+(\d+)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?$", re.I)


class AssemblyError(ValueError):
    """An assembly syntax or operand error, with its source line."""

    def __init__(self, line_number: int, message: str):
        self.line_number = line_number
        self.message = message
        super().__init__(f"line {line_number}: {message}")


@dataclass(frozen=True)
class _Line:
    number: int
    text: str


class _IntegerExpression:
    _binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.LShift: operator.lshift,
        ast.RShift: operator.rshift,
        ast.BitOr: operator.or_,
        ast.BitAnd: operator.and_,
        ast.BitXor: operator.xor,
    }
    _unary = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Invert: operator.invert}

    @classmethod
    def evaluate(cls, text: str) -> int | float:
        try:
            tree = ast.parse(text, mode="eval")
            result = cls._visit(tree.body)
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ValueError(f"invalid numeric expression {text!r}") from exc
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise ValueError(f"invalid numeric expression {text!r}")
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("numeric expression must be finite")
        return result

    @classmethod
    def _visit(cls, node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in cls._unary:
            return cls._unary[type(node.op)](cls._visit(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in cls._binary:
            left, right = cls._visit(node.left), cls._visit(node.right)
            if not isinstance(left, int) or not isinstance(right, int):
                raise ValueError("arithmetic on floating-point literals is not supported")
            return cls._binary[type(node.op)](left, right)
        raise ValueError("only numeric literals and simple integer arithmetic are allowed")


def _without_comment(text: str) -> str:
    for marker in (";", "//", "#"):
        text = text.split(marker, 1)[0]
    return text.strip()


def _expand_repeats(source: str) -> list[_Line]:
    lines = [_Line(i, text) for i, text in enumerate(source.splitlines(), 1)]

    def parse_block(start: int, nested: bool) -> tuple[list[_Line], int]:
        expanded: list[_Line] = []
        i = start
        while i < len(lines):
            current = lines[i]
            text = _without_comment(current.text)
            if text.lower() == ".endrepeat":
                if not nested:
                    raise AssemblyError(current.number, ".endrepeat without .repeat")
                return expanded, i + 1
            match = _REPEAT_RE.match(text)
            if match:
                count = int(match.group(1))
                variable = match.group(2) or "i"
                if count > MAX_REPEAT:
                    raise AssemblyError(current.number, f".repeat limit is {MAX_REPEAT}")
                body, next_i = parse_block(i + 1, True)
                if next_i <= i + 1 or _without_comment(lines[next_i - 1].text).lower() != ".endrepeat":
                    raise AssemblyError(current.number, "unterminated .repeat block")
                for value in range(count):
                    expanded.extend(
                        _Line(line.number, line.text.replace("{" + variable + "}", str(value)))
                        for line in body
                    )
                    if len(expanded) > MAX_INSTRUCTIONS:
                        raise AssemblyError(current.number, f"expanded program exceeds {MAX_INSTRUCTIONS} instructions")
                i = next_i
                continue
            expanded.append(current)
            i += 1
        if nested:
            source_line = lines[start - 1].number if start else 1
            raise AssemblyError(source_line, "unterminated .repeat block")
        return expanded, i

    result, _ = parse_block(0, False)
    return result


def _register(token: str) -> int:
    match = _REGISTER_RE.fullmatch(token.strip())
    if not match:
        raise ValueError(f"expected a register such as r0, got {token!r}")
    index = int(match.group(1))
    if not 0 <= index < 16:
        raise ValueError("register index must be in [0, 16)")
    return index


def _dtype(token: str) -> DataType | None:
    name = token.strip().lower()
    if name in {"inherit", "auto", "none"}:
        return None
    try:
        return _DTYPE_NAMES[name]
    except KeyError as exc:
        raise ValueError(f"unknown data type {token!r}") from exc


def _integer(token: str) -> int:
    value = _IntegerExpression.evaluate(token.strip())
    if not isinstance(value, int):
        raise ValueError("expected an integer")
    return value


def _mask(token: str) -> int:
    if token.strip().lower() == "all":
        return FULL_MASK
    value = _integer(token)
    if not 0 <= value <= FULL_MASK:
        raise ValueError("lane mask must fit in 256 bits")
    return value


def _immediate(token: str, dtype: DataType | None) -> int:
    value = _IntegerExpression.evaluate(token.strip())
    if isinstance(value, float):
        if dtype != DataType.BF16:
            raise ValueError("a floating immediate requires explicit BF16 type")
        return float_to_bf16(value)
    return value


def _operands(text: str, line_number: int) -> tuple[str, list[str]]:
    fields = text.split(None, 1)
    mnemonic = fields[0].lower()
    if len(fields) == 1 or not fields[1].strip():
        return mnemonic, []
    operands = [part.strip() for part in fields[1].split(",")]
    if any(not part for part in operands):
        raise AssemblyError(line_number, "empty operand")
    return mnemonic, operands


def _expect_count(args: Iterable[str], valid: set[int], mnemonic: str) -> None:
    count = len(list(args))
    expected = " or ".join(str(value) for value in sorted(valid))
    if count not in valid:
        raise ValueError(f"{mnemonic} expects {expected} operand(s), got {count}")


def assemble(source: str) -> list[Instruction]:
    """Translate assembly text into Grider instruction records.

    Directives are .dtype, .mask, and compile-time .repeat. A floating literal
    in movi is encoded as BF16 only when the instruction type is explicit.
    """
    program: list[Instruction] = []
    current_dtype: DataType | None = DataType.I32
    current_mask = FULL_MASK

    for line in _expand_repeats(source):
        text = _without_comment(line.text)
        if not text:
            continue
        if text.lower().startswith(".dtype"):
            fields = text.split()
            if len(fields) != 2:
                raise AssemblyError(line.number, "syntax: .dtype <type>")
            try:
                current_dtype = _dtype(fields[1])
            except ValueError as exc:
                raise AssemblyError(line.number, str(exc)) from exc
            continue
        if text.lower().startswith(".mask"):
            fields = text.split(None, 1)
            if len(fields) != 2:
                raise AssemblyError(line.number, "syntax: .mask <all|integer>")
            try:
                current_mask = _mask(fields[1])
            except ValueError as exc:
                raise AssemblyError(line.number, str(exc)) from exc
            continue
        if text.lower() == ".endrepeat" or text.lower().startswith(".repeat"):
            raise AssemblyError(line.number, "repeat directives must be balanced")

        mnemonic, args = _operands(text, line.number)
        try:
            opcode = _OPCODE_NAMES[mnemonic]
        except KeyError as exc:
            raise AssemblyError(line.number, f"unknown instruction {mnemonic!r}") from exc

        try:
            if opcode == Opcode.NOP:
                _expect_count(args, {0}, mnemonic)
                instruction = Instruction(opcode, lane_mask=current_mask)
            elif opcode == Opcode.MOV:
                _expect_count(args, {2}, mnemonic)
                instruction = Instruction(opcode, dst=_register(args[0]), src_a=_register(args[1]),
                                          dtype=current_dtype, lane_mask=current_mask)
            elif opcode == Opcode.MOVI:
                _expect_count(args, {2, 3}, mnemonic)
                dtype = _dtype(args[2]) if len(args) == 3 else current_dtype
                instruction = Instruction(opcode, dst=_register(args[0]), imm=_immediate(args[1], dtype),
                                          dtype=dtype, lane_mask=current_mask)
            elif opcode in {Opcode.LOAD, Opcode.STORE}:
                _expect_count(args, {2}, mnemonic)
                if opcode == Opcode.LOAD:
                    instruction = Instruction(opcode, dst=_register(args[0]), imm=_integer(args[1]),
                                              dtype=current_dtype, lane_mask=current_mask)
                else:
                    instruction = Instruction(opcode, src_a=_register(args[0]), imm=_integer(args[1]),
                                              dtype=current_dtype, lane_mask=current_mask)
            elif opcode == Opcode.NEIGHBOR:
                _expect_count(args, {3}, mnemonic)
                direction = _DIRECTIONS.get(args[2].lower())
                if direction is None:
                    direction = _integer(args[2])
                if not 0 <= direction <= 7:
                    raise ValueError("neighbor direction must be N..NW or a number in [0, 7]")
                instruction = Instruction(opcode, dst=_register(args[0]), src_a=_register(args[1]),
                                          imm=direction, dtype=current_dtype, lane_mask=current_mask)
            elif opcode == Opcode.SEL:
                _expect_count(args, {4, 5}, mnemonic)
                dtype = _dtype(args[4]) if len(args) == 5 else current_dtype
                instruction = Instruction(opcode, dst=_register(args[0]), src_a=_register(args[1]),
                                          src_b=_register(args[2]), src_c=_register(args[3]),
                                          dtype=dtype, lane_mask=current_mask)
            elif opcode in {Opcode.REDUCE_SUM, Opcode.REDUCE_MAX}:
                _expect_count(args, {2, 3}, mnemonic)
                dtype = _dtype(args[2]) if len(args) == 3 else current_dtype
                instruction = Instruction(opcode, dst=_register(args[0]), src_a=_register(args[1]),
                                          dtype=dtype, lane_mask=current_mask)
            else:
                _expect_count(args, {3, 4}, mnemonic)
                dtype = _dtype(args[3]) if len(args) == 4 else current_dtype
                instruction = Instruction(opcode, dst=_register(args[0]), src_a=_register(args[1]),
                                          src_b=_register(args[2]), dtype=dtype, lane_mask=current_mask)
        except (ValueError, TypeError) as exc:
            raise AssemblyError(line.number, str(exc)) from exc

        program.append(instruction)
        if len(program) > MAX_INSTRUCTIONS:
            raise AssemblyError(line.number, f"program exceeds {MAX_INSTRUCTIONS} instructions")
    return program


def assemble_file(path: str | Path) -> list[Instruction]:
    source_path = Path(path)
    return assemble(source_path.read_text(encoding="utf-8"))


def load_kernel(name: str) -> list[Instruction]:
    """Load a bundled grider/programs/<name>.gr source file."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("kernel name may contain only letters, digits, '_' and '-'")
    path = Path(__file__).with_name("programs") / f"{name}.gr"
    if not path.is_file():
        raise FileNotFoundError(f"unknown Grider kernel {name!r}")
    return assemble_file(path)


def execute(tile, program: Iterable[Instruction]) -> int:
    """Run an assembled stream through the functional tile emulator."""
    start = tile.cycles
    for instruction in program:
        tile.step(instruction)
    return tile.cycles - start
