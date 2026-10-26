#!/usr/bin/env python3
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

stat = (OUT / "mapped-stat.txt").read_text()
area_matches = re.findall(
    r"Chip area for module .*?:\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    stat,
)
if not area_matches:
    raise SystemExit("Could not find a Yosys Chip area for module result")
area_um2 = float(area_matches[-1].replace(",", ""))

sta = (OUT / "sta.log").read_text()
number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
slack_matches = re.findall(
    r"(?m)^[ \t]*" + number + r"[ \t]+slack[ \t]+\((?:MET|VIOLATED)\)",
    sta,
    re.IGNORECASE,
)
if not slack_matches:
    slack_matches = re.findall(
        r"slack[ \t]+\((?:MET|VIOLATED)\)[ \t]+" + number,
        sta,
        re.IGNORECASE,
    )
if not slack_matches:
    raise SystemExit("OpenSTA did not report a constrained register-to-register path slack")
worst_slack_ns = min(float(value) for value in slack_matches)
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
- The RTL describes the register file and local SRAM as two 16×132 single-port synchronous memories. The synthesis run maps to the standard-cell Liberty only; it does not provide an SRAM macro Liberty/LEF or a memory compiler. The design therefore reports inferred memories before mapping and standard cells after mapping; the gate-level output is checked for RAM/SRAM macro instances.
- The exported lane_mask width is checked in both Yosys JSON snapshots to ensure the one-lane parameter override took effect.

## Tool versions

{tool_versions}
"""
(OUT / "report.md").write_text(report)
print(report)

