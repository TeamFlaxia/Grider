#!/usr/bin/env python3
"""Run a small, technology-independent Yosys baseline for Grider tiles."""

from __future__ import annotations

import json
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
    mapped = out / "generic.json"
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
synth -top grider_tile -flatten
tee -o {mapped} stat -json
"""
    with log_path.open("w") as log:
        result = subprocess.run(
            ["yosys", "-Q", "-p", commands],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
    if result.returncode:
        tail = log_path.read_text(errors="replace").splitlines()[-80:]
        raise RuntimeError(f"Yosys failed for {name}:\n" + "\n".join(tail))

    premap_counts = read_cell_counts(premap)
    generic_counts = read_cell_counts(mapped)
    memory_count = sum(
        count for cell, count in premap_counts.items() if "mem" in cell.lower()
    )
    ff_count = sum(
        count for cell, count in generic_counts.items() if "dff" in cell.lower()
    )
    return {
        "configuration": name,
        "tile_width": width,
        "tile_height": height,
        "lanes": lanes,
        "architectural_state_bits": lanes * (16 + 16) * 132,
        "premap_memory_cells": memory_count,
        "generic_cell_count": sum(generic_counts.values()),
        "generic_flip_flop_cells": ff_count,
        "premap_cell_types": premap_counts,
        "generic_cell_types": generic_counts,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output(["yosys", "-V"], text=True).strip()
    results = [run_config(name, width, height) for name, width, height in CONFIGS]
    report = {"yosys_version": version, "results": results}
    (OUT / "summary.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# Grider generic synthesis baseline",
        "",
        f"Tool: {version}",
        "",
        "| Configuration | Lanes | Architectural state bits | Premap memory cells | Generic cells | Generic FF cells |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in results:
        lines.append(
            "| {configuration} | {lanes} | {architectural_state_bits:,} | "
            "{premap_memory_cells:,} | {generic_cell_count:,} | "
            "{generic_flip_flop_cells:,} |".format(**item)
        )
    lines.extend(
        [
            "",
            "The generic cell count is a technology-independent logic-size proxy, not physical area in mm².",
            "The premap memory-cell count comes from Yosys before memory mapping.",
            "Fmax is not reported: the repository does not select a target device or standard-cell library, "
            "and has no clock or I/O timing constraints.",
            "",
        ]
    )
    summary = "\n".join(lines)
    (OUT / "summary.md").write_text(summary)
    github_summary = Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY", ""))
    if str(github_summary):
        with github_summary.open("a") as stream:
            stream.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
