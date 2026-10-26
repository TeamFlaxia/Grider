"""Compare Python and RTL for a 2×2 mesh, including all 8 halo directions."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .sim import DataType, Instruction, Mesh, Opcode


ROOT = Path(__file__).resolve().parents[1]
LANES = 256
ALL_LANES = (1 << LANES) - 1


def verify() -> tuple[int, int]:
    iverilog = os.environ.get("IVERILOG") or shutil.which("iverilog")
    vvp = os.environ.get("VVP") or shutil.which("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("Icarus Verilog is required (iverilog and vvp must be on PATH)")

    mesh = Mesh(tiles_x=2, tiles_y=2)
    lines: list[str] = []
    for ty in range(2):
        for tx in range(2):
            base = ty * 2000 + tx * 1000
            values = [base + lane for lane in range(LANES)]
            tile = mesh.tile_at(tx, ty)
            tile.load_register(0, values, DataType.I16)
            for lane, (payload, dtype) in enumerate(tile.read_register_raw(0)):
                lines.append(f"R {tx} {ty} {lane} 0 {payload:032x} {int(dtype):x}")

    program = [Instruction(Opcode.NEIGHBOR, dst=direction + 1, src_a=0,
                           imm=direction, lane_mask=ALL_LANES)
               for direction in range(8)]
    for insn in program:
        lines.append(f"I {int(insn.opcode)} {insn.dst} {insn.src_a} {insn.src_b} {insn.src_c} "
                     f"{insn.imm:032x} f {insn.lane_mask:064x}")
        mesh.step(insn)

    expected: dict[tuple[int, int, int, int], tuple[int, int]] = {}
    for ty in range(2):
        for tx in range(2):
            tile = mesh.tile_at(tx, ty)
            for register in range(9):
                for lane, (payload, dtype) in enumerate(tile.read_register_raw(register)):
                    expected[(tx, ty, lane, register)] = (payload, int(dtype))

    with tempfile.TemporaryDirectory(prefix="grider-mesh-rtl-") as temp:
        tmp = Path(temp)
        stim = tmp / "stimulus.txt"
        executable = tmp / "mesh.vvp"
        stim.write_text("\n".join(lines) + "\n")
        compile_result = subprocess.run(
            [iverilog, "-g2012", "-s", "tb_grider_mesh", "-o", str(executable),
             str(ROOT / "rtl/grider_tile.sv"), str(ROOT / "rtl/grider_mesh.sv"),
             str(ROOT / "rtl/tb_grider_mesh.sv")],
            cwd=ROOT, text=True, capture_output=True,
        )
        if compile_result.returncode:
            raise RuntimeError(f"mesh RTL compile failed:\n{compile_result.stderr[-8000:]}")
        sim = subprocess.run([vvp, str(executable), f"+STIM={stim}"],
                             cwd=ROOT, text=True, capture_output=True)
        if sim.returncode:
            raise RuntimeError(f"mesh simulation failed:\n{sim.stdout[-4000:]}\n{sim.stderr[-4000:]}")

    actual: dict[tuple[int, int, int, int], tuple[int, int]] = {}
    for line in sim.stdout.splitlines():
        fields = line.split()
        if len(fields) == 7 and fields[0] == "R":
            _, tx, ty, lane, register, payload, tag = fields
            actual[(int(tx), int(ty), int(lane), int(register))] = (int(payload, 16), int(tag, 16))
    if actual.keys() != expected.keys():
        raise AssertionError(f"mesh state dump differs: {len(expected)} expected, {len(actual)} received")
    mismatch = [(key, expected[key], actual[key]) for key in expected if expected[key] != actual[key]]
    if mismatch:
        examples = "\n".join(f"{key}: Python={py}, RTL={hw}" for key, py, hw in mismatch[:30])
        raise AssertionError(f"{len(mismatch)} mesh mismatches:\n{examples}")
    return len(program), len(actual)


def main() -> None:
    instructions, words = verify()
    print(f"Python/RTL mesh match: {instructions} directions; {words} register words across 4 tiles")


if __name__ == "__main__":
    main()
