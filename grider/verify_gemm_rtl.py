"""Execute the concrete GEMM lowering in the Python model and tile RTL."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .lowering import (
    OUTPUT_REGISTER, execute_lowered_gemm16, lower_gemm16,
)
from .sim import Tile


ROOT = Path(__file__).resolve().parents[1]
LANES = 256


def _matrices() -> tuple[list[list[float]], list[list[float]]]:
    a = [[float(((row * 3 + col * 5) % 7) - 3) for col in range(16)]
         for row in range(16)]
    b = [[float(((row * 2 + col * 3) % 5) - 2) for col in range(16)]
         for row in range(16)]
    return a, b


def verify() -> tuple[int, int, float]:
    iverilog = os.environ.get("IVERILOG") or shutil.which("iverilog")
    vvp = os.environ.get("VVP") or shutil.which("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("Icarus Verilog is required (iverilog and vvp must be on PATH)")

    a, b = _matrices()
    result = execute_lowered_gemm16(a, b)
    program = lower_gemm16(a, b)
    tile = Tile()
    lines: list[str] = []
    for insn in program:
        dtype = 0xF if insn.dtype is None else int(insn.dtype)
        lines.append(
            f"I {int(insn.opcode)} {insn.dst} {insn.src_a} {insn.src_b} {insn.src_c} "
            f"{insn.imm & ((1 << 128) - 1):032x} {dtype:x} {insn.lane_mask:064x}"
        )
        tile.step(insn)

    rtl = ROOT / "rtl" / "grider_tile.sv"
    tb = ROOT / "rtl" / "tb_grider_tile.sv"
    with tempfile.TemporaryDirectory(prefix="grider-gemm-rtl-") as temp:
        temp_path = Path(temp)
        stimulus = temp_path / "stimulus.txt"
        executable = temp_path / "tile.vvp"
        stimulus.write_text("\n".join(lines) + "\n")
        compiled = subprocess.run(
            [iverilog, "-g2012", "-s", "tb_grider_tile", "-o", str(executable), str(rtl), str(tb)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if compiled.returncode:
            raise RuntimeError(f"iverilog compile failed:\n{compiled.stderr[-8000:]}")
        simulated = subprocess.run(
            [vvp, str(executable), f"+STIM={stimulus}"],
            cwd=ROOT, text=True, capture_output=True,
        )
        if simulated.returncode:
            raise RuntimeError(f"RTL simulation failed:\n{simulated.stdout[-4000:]}\n{simulated.stderr[-4000:]}")

    rtl_outputs: dict[int, tuple[int, int]] = {}
    for line in simulated.stdout.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == "R":
            lane, register = int(fields[1]), int(fields[2])
            if register == OUTPUT_REGISTER:
                rtl_outputs[lane] = (int(fields[3], 16), int(fields[4], 16))
    expected = tile.read_register_raw(OUTPUT_REGISTER)
    if len(rtl_outputs) != LANES:
        raise AssertionError(f"expected {LANES} RTL outputs, found {len(rtl_outputs)}")
    for lane, (payload, dtype) in enumerate(expected):
        if rtl_outputs[lane] != (payload, int(dtype)):
            raise AssertionError(
                f"lane {lane} differs: Python={(payload, int(dtype))}, RTL={rtl_outputs[lane]}"
            )
    return result.instruction_count, result.estimated_rtl_cycles, result.max_absolute_error


def main() -> None:
    instructions, estimated_cycles, error = verify()
    print(
        "RTL/Python GEMM match: "
        f"{instructions} instructions; estimated {estimated_cycles} RTL cycles; "
        f"max BF16 reference error {error:g}"
    )


if __name__ == "__main__":
    main()
