"""Compare the Python tile emulator with the SystemVerilog tile via Icarus.

Run from the repository root with `python -m grider.verify_rtl`. The check uses
the actual tile RTL, a host/debug load port and a generated common instruction
stream, then compares every register and local SRAM word in all 256 cells.
"""

from __future__ import annotations

import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

from .sim import DataType, Instruction, Opcode, Tile, bf16_to_float


ROOT = Path(__file__).resolve().parents[1]
LANES = 256
ALL_LANES = (1 << LANES) - 1


def _stimulus(tile: Tile, integer_program: list[Instruction],
              bf16_program: list[Instruction]) -> str:
    lines: list[str] = []

    def write(kind: str, lane: int, index: int, payload: int, dtype: DataType) -> None:
        lines.append(f"{kind} {lane} {index} {payload:032x} {int(dtype):x}")

    inputs0 = [lane % 16 - 8 for lane in range(LANES)]
    inputs1 = [(lane * 7) % 17 - 8 for lane in range(LANES)]
    inputs2 = [lane % 5 - 2 for lane in range(LANES)]
    predicates = [int(lane % 3 == 0) for lane in range(LANES)]
    sram = [lane * 5 - 300 for lane in range(LANES)]
    for register, values, dtype in (
        (0, inputs0, DataType.I8), (1, inputs1, DataType.I8),
        (2, inputs2, DataType.I8), (3, predicates, DataType.PRED),
    ):
        tile.load_register(register, values, dtype)
        for lane, (payload, tag) in enumerate(tile.read_register_raw(register)):
            write("R", lane, register, payload, tag)
    tile.load_sram(0, sram, DataType.I16)
    for lane, (payload, tag) in enumerate(tile.read_sram_raw(0)):
        write("S", lane, 0, payload, tag)

    def run(program: list[Instruction]) -> None:
        for insn in program:
            dtype = 0xF if insn.dtype is None else int(insn.dtype)
            lines.append(
                f"I {int(insn.opcode)} {insn.dst} {insn.src_a} {insn.src_b} {insn.src_c} "
                f"{insn.imm & ((1 << 128) - 1):032x} {dtype:x} {insn.lane_mask:064x}"
            )
            tile.step(insn)

    run(integer_program)

    # BF16 input loading is represented by the same host/debug path on both sides.
    rng = random.Random(0x6A1D3)

    def random_finite_bf16() -> float:
        exponent = rng.choice([0, 0, 1, 2, 3, rng.randrange(1, 255),
                               rng.randrange(1, 255), 120, 126, 127, 128, 253, 254])
        raw = (rng.randrange(2) << 15) | (exponent << 7) | rng.randrange(128)
        return bf16_to_float(raw)

    directed = {
        0: [0x0000, 0x8000, 0x0001, 0x007f, 0x0080, 0x3f80, 0xbf80, 0x7f7f,
            0xff7f, 0x3f00, 0x3f80, 0x3f81, 0x0081, 0x8080, 0x0100, 0x4000,
            0x7fc0, 0xffc1, 0x7f80, 0xff80, 0x0000, 0x8000],
        1: [0x8000, 0x8000, 0x0001, 0x0001, 0x0080, 0x3f80, 0x3f80, 0x7f7f,
            0x7f7f, 0x3f80, 0xbf80, 0x3f80, 0x007f, 0x0080, 0x0080, 0x4000,
            0x3f80, 0x3f80, 0x0000, 0x7f80, 0xff80, 0x7fc0],
        2: [0x3f08] * LANES,
        4: [0x8000, 0x0000, 0x0001, 0x007f, 0x0080, 0xbf80, 0x3f80, 0x7f7f,
            0xff7f, 0x3f80, 0x3f80, 0xbf80, 0x0001, 0x807f, 0x0080, 0xc000,
            0x7fc0, 0xff80, 0x7f80, 0xff80, 0x0000, 0x8000],
    }
    bf16_inputs = {}
    for register, pattern in directed.items():
        values = [bf16_to_float(raw) for raw in pattern]
        values.extend(random_finite_bf16() for _ in range(LANES - len(values)))
        bf16_inputs[register] = values
    for register, values in bf16_inputs.items():
        tile.load_register(register, values, DataType.BF16)
        for lane, (payload, tag) in enumerate(tile.read_register_raw(register)):
            write("R", lane, register, payload, tag)

    run(bf16_program)
    return "\n".join(lines) + "\n"


def _program() -> list[Instruction]:
    mask = sum(1 << lane for lane in range(LANES) if lane % 3 == 1)
    reduction_mask = 0
    for lane in range(LANES):
        row, col = divmod(lane, 16)
        if (row % 4 == 0 and col in (1, 4, 7, 10, 13)) or \
           (row % 4 == 1 and col == 7) or \
           (row % 4 == 3 and col % 2 == 0):
            reduction_mask |= 1 << lane
    return [
        Instruction(Opcode.ADD, dst=4, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.MAC, dst=2, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.SUB, dst=5, src_a=0, src_b=1, dtype=DataType.I4),
        Instruction(Opcode.MUL, dst=6, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.AND, dst=7, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.OR, dst=8, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.SHR, dst=9, src_a=0, src_b=1, dtype=DataType.I8),
        Instruction(Opcode.NEIGHBOR, dst=10, src_a=4, imm=2),
        Instruction(Opcode.NEIGHBOR, dst=11, src_a=4, imm=0),
        Instruction(Opcode.STORE, src_a=4, imm=2),
        Instruction(Opcode.LOAD, dst=12, imm=2),
        Instruction(Opcode.LOAD, dst=13, imm=0),
        Instruction(Opcode.ADD, dst=14, src_a=0, src_b=1, dtype=DataType.I8,
                    lane_mask=mask),
        Instruction(Opcode.SEL, dst=15, src_a=3, src_b=0, src_c=1,
                    dtype=DataType.I8),
        Instruction(Opcode.REDUCE_SUM, dst=4, src_a=0, dtype=DataType.I8),
        Instruction(Opcode.REDUCE_MAX, dst=5, src_a=0, dtype=DataType.I8),
        Instruction(Opcode.REDUCE_SUM, dst=6, src_a=1, dtype=DataType.I8,
                    lane_mask=reduction_mask),
        Instruction(Opcode.REDUCE_MAX, dst=7, src_a=0, dtype=DataType.I8,
                    lane_mask=reduction_mask),
        Instruction(Opcode.MOVI, dst=1, imm=0x80, dtype=DataType.I8),
    ]


def _bf16_program() -> list[Instruction]:
    return [
        Instruction(Opcode.ADD, dst=5, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.SUB, dst=6, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.MUL, dst=7, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.MAC, dst=4, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.MIN, dst=8, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.MAX, dst=9, src_a=0, src_b=1, dtype=DataType.BF16),
        Instruction(Opcode.REDUCE_SUM, dst=10, src_a=0, dtype=DataType.BF16),
        Instruction(Opcode.REDUCE_MAX, dst=11, src_a=1, dtype=DataType.BF16),
        Instruction(Opcode.AND, dst=12, src_a=0, src_b=2, dtype=DataType.BF16),
        Instruction(Opcode.OR, dst=13, src_a=0, src_b=2, dtype=DataType.BF16),
        Instruction(Opcode.XOR, dst=14, src_a=0, src_b=2, dtype=DataType.BF16),
        Instruction(Opcode.SHL, dst=15, src_a=0, src_b=2, dtype=DataType.BF16),
        Instruction(Opcode.SHR, dst=3, src_a=0, src_b=2, dtype=DataType.BF16),
    ]


def _expected(tile: Tile) -> dict[tuple[str, int, int], tuple[int, int]]:
    expected: dict[tuple[str, int, int], tuple[int, int]] = {}
    for register in range(16):
        for lane, (payload, dtype) in enumerate(tile.read_register_raw(register)):
            expected[("R", lane, register)] = (payload, int(dtype))
    for address in range(16):
        for lane, (payload, dtype) in enumerate(tile.read_sram_raw(address)):
            expected[("S", lane, address)] = (payload, int(dtype))
    return expected


def verify() -> tuple[int, int]:
    iverilog = os.environ.get("IVERILOG") or shutil.which("iverilog")
    vvp = os.environ.get("VVP") or shutil.which("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("Icarus Verilog is required (iverilog and vvp must be on PATH)")

    tile = Tile()
    integer_program = _program()
    bf16_program = _bf16_program()
    program = integer_program + bf16_program
    stimulus = _stimulus(tile, integer_program, bf16_program)
    expected = _expected(tile)
    tb = ROOT / "rtl" / "tb_grider_tile.sv"
    rtl = ROOT / "rtl" / "grider_tile.sv"

    with tempfile.TemporaryDirectory(prefix="grider-rtl-") as temp:
        temp_path = Path(temp)
        stim_path = temp_path / "stimulus.txt"
        executable = temp_path / "tile.vvp"
        stim_path.write_text(stimulus)
        compiled = subprocess.run(
            [iverilog, "-g2012", "-s", "tb_grider_tile", "-o", str(executable), str(rtl), str(tb)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if compiled.returncode:
            raise RuntimeError(f"iverilog compile failed:\n{compiled.stderr[-8000:]}")
        simulated = subprocess.run(
            [vvp, str(executable), f"+STIM={stim_path}"],
            cwd=ROOT, text=True, capture_output=True,
        )
        if simulated.returncode:
            raise RuntimeError(f"RTL simulation failed:\n{simulated.stdout[-4000:]}\n{simulated.stderr[-4000:]}")

    seen: dict[tuple[str, int, int], tuple[int, int]] = {}
    for line in simulated.stdout.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] in {"R", "S"}:
            kind, lane, index, payload, tag = parts
            seen[(kind, int(lane), int(index))] = (int(payload, 16), int(tag, 16))
    if seen.keys() != expected.keys():
        missing = expected.keys() - seen.keys()
        extra = seen.keys() - expected.keys()
        raise AssertionError(f"state dump mismatch: {len(missing)} missing, {len(extra)} extra entries")
    mismatches = [(key, expected[key], seen[key]) for key in expected if expected[key] != seen[key]]
    if mismatches:
        sample = "\n".join(f"{k}: Python={py!r} RTL={rtl!r}" for k, py, rtl in mismatches[:80])
        raise AssertionError(f"{len(mismatches)} Python/RTL state mismatches:\n{sample}")
    return len(program), len(seen)


def main() -> None:
    instructions, state_words = verify()
    print(f"Python/RTL match: {instructions} instructions; {state_words} register/SRAM words across 256 cells")


if __name__ == "__main__":
    main()

