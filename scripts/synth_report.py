#!/usr/bin/env python3
"""Report a technology-independent Yosys coarse-synthesis baseline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "rtl" / "grider_tile.sv"
OUT = ROOT / "build" / "synthesis"
CONFIGS = (("pe-1x1", 1, 1), ("tile-2x2", 2, 2))


def read_cell_counts(path: Path) -> dict[str, int]:
    report = json.loads(path.read_text())
    counts: dict[str, int] = {}
    for module in report.get("modules", {}).values():
        for cell, count in module.get("num_cells_by_type", {}).items():
            counts[cell] = counts.get(cell, 0) + int(count)
    return counts


def run_config(name: str, width: int, height: int) -> dict[str, object]:
    lanes = width * height
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    premap = out / "premap.json"
    coarse = out / "coarse.json"
    log_path = out / "yosys.log"
    commands = f"""
read_verilog -sv {RTL}
chparam -set TILE_W {width} -set TILE_H {height} -set LANES {lanes} grider_tile
hierarchy -check -purge -top grider_tile
proc
opt
memory_dff
memory_collect
tee -o {premap} stat -json
synth -top grider_tile -flatten -run begin:coarse
tee -o {coarse} stat -json
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
        raise RuntimeError(f"Yosys failed for {name}:\n" + "\n".join(tail))

    premap_counts = read_cell_counts(premap)
    coarse_counts = read_cell_counts(coarse)
    memory_count = sum(
        count for cell, count in premap_counts.items() if "mem" in cell.lower()
    )
    multiplier_count = sum(
        count for cell, count in coarse_counts.items()
        if "mul" in cell.lower() or "macc" in cell.lower()
    )
    return {
        "configuration": name,
        "tile_width": width,
        "tile_height": height,
        "lanes": lanes,
        "architectural_state_bits": lanes * (16 + 16) * 132,
        "premap_memory_cells": memory_count,
        "coarse_cell_count": sum(coarse_counts.values()),
        "coarse_multiplier_cells": multiplier_count,
        "premap_cell_types": premap_counts,
        "coarse_cell_types": coarse_counts,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output(["yosys", "-V"], text=True).strip()
    results = [run_config(name, width, height) for name, width, height in CONFIGS]
    report = {"yosys_version": version, "results": results}
    (OUT / "summary.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# Grider Yosys coarse-synthesis baseline",
        "",
        f"Tool: {version}",
        "",
        "| Configuration | Lanes | State bits | Premap memory cells | Coarse cells | Multiplier/MACC cells |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in results:
        lines.append(
            "| {configuration} | {lanes} | {architectural_state_bits:,} | "
            "{premap_memory_cells:,} | {coarse_cell_count:,} | "
            "{coarse_multiplier_cells:,} |".format(**item)
        )
    lines.extend(
        [
            "",
            "Coarse Yosys cell counts are structural metrics, not physical area.",
            "Fmax is not reported because this repository does not select a target device or cell library "
            "and has no clock or I/O timing constraints.",
            "",
        ]
    )
    summary = "\n".join(lines)
    (OUT / "summary.md").write_text(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as stream:
            stream.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
