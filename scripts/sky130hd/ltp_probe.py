#!/usr/bin/env python3
"""Measure the longest topological path of a patched copy of the tile RTL.

Usage: python3 scripts/sky130hd/ltp_probe.py <patch-name>
The patch is applied to a copy under /tmp/ltp-probe so the repository is
untouched. Prints the path length in levels.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "rtl/grider_tile.sv"

PATCHES = {
    # Replace the DOT_ROW tree products with a constant: removes every
    # f32_mul instance that the row dot product creates.
    "nodot": [
        (r"f32_mul\(bf16_to_f32\(operand_a\[dot_y\*TILE_W\+dot_x\]\[15:0\]\),\s*"
         r"bf16_to_f32\(operand_b\[dot_y\*TILE_W\+dot_x\]\[15:0\]\)\)", "32'h3F800000"),
        (r"f32_mul\(operand_a\[dot_y\*TILE_W\+dot_x\]\[31:0\],\s*"
         r"operand_b\[dot_y\*TILE_W\+dot_x\]\[31:0\]\)", "32'h3F800000"),
    ],
    # Replace the ALU (main always_comb) multipliers.
    "noalumul": [
        (r"f32_mul\(lane_a\[lane\]\[31:0\],\s*lane_b\[lane\]\[31:0\]\)", "32'h3F800000"),
        (r"f32_mul\(bf16_to_f32\(lane_a\[lane\]\[15:0\]\),\s*"
         r"bf16_to_f32\(lane_b\[lane\]\[15:0\]\)\)", "32'h3F800000"),
    ],
    # Replace the ALU adders as well: leaves only the muxes and the
    # sign-extension logic on the path.
    "noalu": [
        (r"f32_mul\(lane_a\[lane\]\[31:0\],\s*lane_b\[lane\]\[31:0\]\)", "32'h3F800000"),
        (r"f32_mul\(bf16_to_f32\(lane_a\[lane\]\[15:0\]\),\s*"
         r"bf16_to_f32\(lane_b\[lane\]\[15:0\]\)\)", "32'h3F800000"),
        (r"f32_add\(lane_a\[lane\]\[31:0\],\s*lane_b\[lane\]\[31:0\]\)", "32'h3F800000"),
        (r"f32_add\(lane_a\[lane\]\[31:0\],\s*\{~lane_b\[lane\]\[31\],\s*lane_b\[lane\]\[30:0\]\}\)",
         "32'h3F800000"),
        (r"bf16_add\(lane_a\[lane\]\[15:0\],\s*lane_b\[lane\]\[15:0\]\)", "16'h3F80"),
        (r"bf16_add\(lane_a\[lane\]\[15:0\],\s*\{~lane_b\[lane\]\[15\],\s*lane_b\[lane\]\[14:0\]\}\)",
         "16'h3F80"),
        (r"bf16_mul\(lane_a\[lane\]\[15:0\],\s*lane_b\[lane\]\[15:0\]\)", "16'h3F80"),
    ],
    # Swap the operands of the ALU MAC multipliers. The result is unchanged
    # (the multiply is commutative) but the two call sites no longer have
    # identical inputs, so the synthesis cannot merge them into one chain.
    "swapped": [
        (r"f32_mul\(lane_a\[lane\]\[31:0\],\s*lane_b\[lane\]\[31:0\]\)\}", "32'h3F800000}"),
        (r"f32_mul\(operand_acc\[lane\]\[31:0\],\s*", "f32_mul(lane_b[lane][31:0], lane_a[lane][31:0]))} else if (0) { lane_result[lane] = {96'b0, f32_add(1'b0, "),
    ],
    "swapped2": [
        (r"f32_mul\(lane_a\[lane\]\[31:0\],\s*lane_b\[lane\]\[31:0\]\)",
         "f32_mul(lane_b[lane][31:0], lane_a[lane][31:0])"),
        (r"f32_mul\(bf16_to_f32\(lane_a\[lane\]\[15:0\]\),\s*"
         r"bf16_to_f32\(lane_b\[lane\]\[15:0\]\)\)",
         "f32_mul(bf16_to_f32(lane_b[lane][15:0]), bf16_to_f32(lane_a[lane][15:0]))"),
    ],
}


def apply_patch(text: str, name: str) -> str:
    if name == "base":
        return text
    if name not in PATCHES:
        raise SystemExit(f"unknown patch {name}")
    for pattern, replacement in PATCHES[name]:
        text, count = re.subn(pattern, replacement, text)
        if count == 0:
            raise SystemExit(f"patch {name}: pattern not found: {pattern}")
        print(f"  {count} x {pattern[:48]}")
    return text


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "base"
    out_dir = Path("/tmp/ltp-probe")
    (out_dir / "rtl").mkdir(parents=True, exist_ok=True)
    text = apply_patch(SRC.read_text(), name)
    (out_dir / "rtl/grider_tile.sv").write_text(text)
    script = out_dir / "ltp.ys"
    script.write_text(
        "read_verilog -defer -sv rtl/grider_tile.sv\n"
        "hierarchy -check -chparam TILE_W 1 -chparam TILE_H 1 -chparam LANES 1 -top grider_tile\n"
        "proc\nopt\n"
        "tee -o ltp.txt ltp -noff\n"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{out_dir}:/work", "-w", "/work",
         "grider-eda-trixie:local", "bash", "-c",
         "yosys -s ltp.ys >/dev/null 2>&1; "
         "echo LEVELS=$(grep -c '^ *[0-9]*:' ltp.txt); "
         "grep -oE 'rtl/grider_tile\\.sv:[0-9]+' ltp.txt | sort | uniq -c | sort -rn | head -12"],
        capture_output=True, text=True,
    )
    print(f"{name}: {result.stdout.strip() or result.stderr.strip()[-300:]}")


if __name__ == "__main__":
    main()
