#!/usr/bin/env python3
"""Report Yosys memory inference and structural state for one Grider PE."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "rtl" / "grider_tile.sv"
OUT = ROOT / "build" / "synthesis"
WIDTH = 1
HEIGHT = 1
LANES = WIDTH * HEIGHT


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    premap = OUT / "premap.json"
    log_path = OUT / "yosys.log"
    commands = f"""
read_verilog -sv {RTL}
chparam -set TILE_W {WIDTH} -set TILE_H {HEIGHT} -set LANES {LANES} grider_tile
hierarchy -check -purge -top grider_tile
proc
opt
memory_dff
memory_collect
tee -o {premap} stat -json
"""
    with log_path.open("w") as log:
        result = subprocess.run(
            ["yosys", "-Q", "-p", commands],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    if result.returncode:
        tail = log_path.read_text(errors="replace").splitlines()[-80:]
        raise RuntimeError(f"Yosys failed:\n" + "\n".join(tail))

    report = json.loads(premap.read_text())
    cell_counts: dict[str, int] = {}
    memory_bits = 0
    for module in report.get("modules", {}).values():
        memory_bits += int(module.get("num_memory_bits", 0))
        for cell, count in module.get("num_cells_by_type", {}).items():
            cell_counts[cell] = cell_counts.get(cell, 0) + int(count)

    memory_cells = sum(
        count for cell, count in cell_counts.items() if "mem" in cell.lower()
    )
    async_cells = sum(
        count for cell, count in cell_counts.items() if "adff" in cell.lower()
    )
    state_bits = LANES * (16 + 16) * 132
    summary = f"""# Grider Yosys memory-inference report

Tool: {subprocess.check_output(["yosys", "-V"], text=True).strip()}

| Configuration | Lanes | Architectural state bits | Yosys memory cells | Yosys memory bits | Async-reset cell types |
| --- | ---: | ---: | ---: | ---: | ---: |
| {WIDTH}×{HEIGHT} PE | {LANES} | {state_bits:,} | {memory_cells:,} | {memory_bits:,} | {async_cells:,} |

This report stops before memory mapping. It measures memory inference and structural state, not physical area.
Fmax and physical area require a target device or standard-cell library and timing constraints.
"""
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "yosys_version": subprocess.check_output(
                    ["yosys", "-V"], text=True
                ).strip(),
                "lanes": LANES,
                "architectural_state_bits": state_bits,
                "memory_cells": memory_cells,
                "memory_bits": memory_bits,
                "async_reset_cells": async_cells,
                "cell_types": cell_counts,
            },
            indent=2,
        )
        + "\n"
    )
    (OUT / "summary.md").write_text(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a") as stream:
            stream.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
