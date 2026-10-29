#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

import json
import re
from pathlib import Path

OUT = Path("build/sky130hd")
CLOCK_PERIOD_NS = 100.0


def parameter_int(value):
    if isinstance(value, int):
        return value
    value = str(value)
    if value and set(value) <= {"0", "1"}:
        return int(value, 2)
    return int(value, 0)


def all_cells(data):
    for module in data.get("modules", {}).values():
        for cell in module.get("cells", {}).values():
            yield cell


def chip_area(stat_path):
    stat = stat_path.read_text()
    matches = re.findall(
        r"Chip area for module .*?:\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        stat,
    )
    if not matches:
        raise SystemExit(f"Could not find Yosys cell area in {stat_path}")
    return float(matches[-1].replace(",", ""))


def worst_slack(sta_path):
    sta = sta_path.read_text()
    number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    matches = re.findall(
        r"(?m)^[ \t]*" + number + r"[ \t]+slack[ \t]+\((?:MET|VIOLATED)\)",
        sta,
        re.IGNORECASE,
    )
    if not matches:
        matches = re.findall(
            r"slack[ \t]+\((?:MET|VIOLATED)\)[ \t]+" + number,
            sta,
            re.IGNORECASE,
        )
    if not matches:
        raise SystemExit(f"OpenSTA did not report register-to-register slack in {sta_path}")
    return min(float(value) for value in matches)


def lef_macro_area(path, macro_name):
    text = path.read_text()
    block_match = re.search(
        rf"(?im)^\s*MACRO\s+{re.escape(macro_name)}\s*$([\s\S]*?)^\s*END\s+{re.escape(macro_name)}\s*$",
        text,
    )
    if not block_match:
        raise SystemExit(f"LEF {path} does not define macro {macro_name}")
    size_match = re.search(
        r"(?im)^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;",
        block_match.group(1),
    )
    if not size_match:
        raise SystemExit(f"LEF {path} has no size for macro {macro_name}")
    return float(size_match.group(1)) * float(size_match.group(2))


pre = json.loads((OUT / "pre-map.json").read_text())
mapped = json.loads((OUT / "mapped.json").read_text())

for label, data in (("pre-map", pre), ("mapped", mapped)):
    top = data.get("modules", {}).get("grider_tile")
    if top is None:
        raise SystemExit(f"{label} JSON does not contain grider_tile")
    lane_mask_bits = len(top.get("ports", {}).get("lane_mask", {}).get("bits", []))
    if lane_mask_bits != 1:
        raise SystemExit(
            f"{label} synthesis did not apply LANES=1: lane_mask has {lane_mask_bits} bits"
        )

memories = [cell for cell in all_cells(pre) if cell.get("type", "").startswith("$mem")]
memory_bits = 0
memory_shapes = []
memory_dimensions = []
for cell in memories:
    params = cell.get("parameters", {})
    width = params.get("WIDTH")
    size = params.get("SIZE")
    if width is not None and size is not None:
        width = parameter_int(width)
        size = parameter_int(size)
        memory_bits += width * size
        memory_shapes.append(f"{size} words × {width} bit")
        memory_dimensions.append((size, width))

if sum(1 for size, width in memory_dimensions if size == 16 and width == 132) != 2:
    raise SystemExit(
        "Expected two separate 16×132 abstract memories for the register file and local SRAM"
    )

mapped_cells = list(all_cells(mapped))
mapped_cell_count = len(mapped_cells)
mapped_ram_cells = [
    cell for cell in mapped_cells
    if re.search(r"(?:^|__)(?:s?ram|memory)", cell.get("type", ""), re.IGNORECASE)
]
flop_count = sum(
    1 for cell in mapped_cells
    if re.match(r"sky130_fd_sc_hd__(?:df|edf|sdf|sedf)", cell.get("type", ""))
)

area_um2 = chip_area(OUT / "mapped-stat.txt")
worst_slack_ns = worst_slack(OUT / "sta.log")
critical_period_ns = CLOCK_PERIOD_NS - worst_slack_ns
if critical_period_ns <= 0:
    raise SystemExit(f"Invalid critical period derived from slack: {critical_period_ns} ns")
fmax_mhz = 1000.0 / critical_period_ns

pdk_commit_file = OUT / "pdk-commit.txt"
pdk_commit = pdk_commit_file.read_text().strip() if pdk_commit_file.exists() else "unspecified"
tool_versions = (OUT / "tool-versions.txt").read_text().strip()

abstract_memory = (
    f"{len(memories)} cell(s), {memory_bits} bit(s) ({', '.join(memory_shapes)})"
    if memories else "0 cells (RTL arrays were not retained as abstract Yosys memories)"
)

macro_report = ""
macro_json_path = OUT / "macro-mapped.json"
if macro_json_path.exists():
    macro_mapped = json.loads(macro_json_path.read_text())
    macro_top = macro_mapped.get("modules", {}).get("grider_tile")
    if macro_top is None:
        raise SystemExit("SRAM22 JSON does not contain grider_tile")
    if len(macro_top.get("ports", {}).get("lane_mask", {}).get("bits", [])) != 1:
        raise SystemExit("SRAM22 synthesis did not apply LANES=1")
    macro_cells = list(all_cells(macro_mapped))
    macro_types = {}
    for cell in macro_cells:
        cell_type = cell.get("type", "")
        if cell_type.startswith("sram22_"):
            macro_types[cell_type] = macro_types.get(cell_type, 0) + 1
    expected_macro_types = {
        "sram22_64x128m4w8": 2,
        "sram22_64x8m4w8": 2,
    }
    if macro_types != expected_macro_types:
        raise SystemExit(f"Unexpected SRAM22 instances: {macro_types}")

    macro_data_dir = OUT / "sram22" / "sram22_64x128m4w8"
    macro_tag_dir = OUT / "sram22" / "sram22_64x8m4w8"
    macro_area_um2 = 2 * lef_macro_area(
        macro_data_dir / "sram22_64x128m4w8.lef", "sram22_64x128m4w8"
    ) + 2 * lef_macro_area(
        macro_tag_dir / "sram22_64x8m4w8.lef", "sram22_64x8m4w8"
    )
    macro_std_area_um2 = chip_area(OUT / "macro-mapped-stat.txt")
    macro_slack_ns = worst_slack(OUT / "sta-macro.log")
    macro_period_ns = CLOCK_PERIOD_NS - macro_slack_ns
    if macro_period_ns <= 0:
        raise SystemExit(f"Invalid SRAM22 critical period: {macro_period_ns} ns")
    macro_fmax_mhz = 1000.0 / macro_period_ns
    macro_seq_count = sum(
        1 for cell in macro_cells
        if re.match(r"sky130_fd_sc_hd__(?:df|edf|sdf|sedf)", cell.get("type", ""))
    )
    macro_capacity_bits = 2 * (64 * 128 + 64 * 8)
    macro_commit_file = OUT / "sram22-commit.txt"
    macro_commit = macro_commit_file.read_text().strip() if macro_commit_file.exists() else "unspecified"
    macro_report = f"""
## SRAM22 hard-macro experiment

| Measurement | Result |
|---|---:|
| Physical SRAM macro instances | {sum(macro_types.values())} (2 payload + 2 tag) |
| SRAM capacity allocated | {macro_capacity_bits:,} bits for 4,224 logical bits |
| Physical SRAM macro area from LEF | {macro_area_um2:,.2f} µm² |
| Standard-cell area | {macro_std_area_um2:,.2f} µm² |
| Combined cell and macro area | {macro_std_area_um2 + macro_area_um2:,.2f} µm² |
| Standard-cell sequential instances | {macro_seq_count:,} |
| Worst register-to-register slack at 100 ns | {macro_slack_ns:.4f} ns |
| Derived pre-layout Fmax | {macro_fmax_mhz:.3f} MHz |

This option uses SRAM22-generated 64×128-bit payload and 64×8-bit tag macros, with only addresses 0–15 used. The generated macro views come from SRAM22 commit `{macro_commit}`. This remains a pre-layout estimate; the macros are not placed or routed in this flow.
"""

report = f"""# Sky130HD staged-memory estimate: one PE

| Measurement | Result |
|---|---:|
| Configuration | TILE_W=1, TILE_H=1, LANES=1 |
| Mapped Sky130HD standard-cell area | {area_um2:,.2f} µm² |
| Mapped standard-cell instances | {mapped_cell_count:,} |
| Mapped flip-flop instances | {flop_count:,} |
| Abstract Yosys memories after memory_collect | {abstract_memory} |
| RAM/SRAM macro instances in mapped netlist | {len(mapped_ram_cells)} |
| Worst internal register-to-register slack at 100 ns | {worst_slack_ns:.4f} ns |
| Derived pre-layout Fmax | {fmax_mhz:.3f} MHz |

## Conditions

- Library: sky130_fd_sc_hd__tt_025C_1v80.lib, PDK repository commit {pdk_commit} (TT, 25 °C, 1.80 V).
- Area is Yosys stat -liberty after Sky130HD technology mapping. It excludes placement-only cells, clock-tree cells, routing, and physical-design overhead.
- OpenSTA uses a 100 ns ideal clock, 100 ps clock transition, and zero clock uncertainty. Fmax is derived as 1000 / (100 ns - worst slack).
- This is a pre-layout, register-to-register estimate. No placed design or extracted SPEF parasitics are supplied, so it is not a routed Fmax.
- The default RTL path is checked as two 16×132 single-port synchronous memories, then mapped to standard cells. A second path instantiates SRAM22 hard macros and maps with generated Liberty/LEF views; both netlists are measured separately.
- The exported lane_mask width is checked in both Yosys JSON snapshots to ensure the one-lane parameter override took effect.

## Tool versions

{tool_versions}

{macro_report}
"""
(OUT / "report.md").write_text(report)
print(report)

