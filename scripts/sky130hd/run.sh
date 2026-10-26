#!/usr/bin/env bash
set -euo pipefail

mkdir -p build/sky130hd
if [[ ! -s "$SKY130HD_LIB" ]]; then
  echo "Missing Sky130HD Liberty file: $SKY130HD_LIB" >&2
  exit 2
fi

{
  yosys -V
  docker run --rm openroad/orfs:latest bash -lc \
    'source /OpenROAD-flow-scripts/env.sh && openroad -version'
} > build/sky130hd/tool-versions.txt 2>&1

cat > build/sky130hd/param-check.ys <<'YOSYS'
read_verilog -defer -sv rtl/grider_tile.sv
hierarchy -check -chparam TILE_W 1 -chparam TILE_H 1 -chparam LANES 1 -top grider_tile
proc
write_json build/sky130hd/param-check.json
YOSYS

yosys -s build/sky130hd/param-check.ys 2>&1 | tee build/sky130hd/param-check.log
python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("build/sky130hd/param-check.json").read_text())
top = data.get("modules", {}).get("grider_tile")
if top is None:
    raise SystemExit("Yosys parameter check did not elaborate grider_tile")
width = len(top.get("ports", {}).get("lane_mask", {}).get("bits", []))
if width != 1:
    raise SystemExit(f"Expected LANES=1 before synthesis, got lane_mask width {width}")
print("Confirmed one-lane elaboration before synthesis.")
PY

cat > build/sky130hd/memory.ys <<'YOSYS'
read_verilog -defer -sv rtl/grider_tile.sv
hierarchy -check -chparam TILE_W 1 -chparam TILE_H 1 -chparam LANES 1 -top grider_tile
proc
opt
memory_dff
memory_share
memory_collect
write_json build/sky130hd/pre-map.json
tee -o build/sky130hd/pre-map-stat.txt stat
YOSYS

cat > build/sky130hd/map.ys <<'YOSYS'
read_verilog -defer -sv rtl/grider_tile.sv
hierarchy -check -chparam TILE_W 1 -chparam TILE_H 1 -chparam LANES 1 -top grider_tile
synth -top grider_tile -noabc
dfflibmap -liberty build/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib
abc -liberty build/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib
clean
tee -o build/sky130hd/mapped-stat.txt stat -liberty build/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib
write_json build/sky130hd/mapped.json
# Keep RTL port names, but hide complex source-derived internal names before STA export.
rename -hide
write_verilog -noattr -noexpr build/sky130hd/grider_tile_mapped.v
YOSYS

yosys -s build/sky130hd/memory.ys 2>&1 | tee build/sky130hd/memory.log
yosys -s build/sky130hd/map.ys 2>&1 | tee build/sky130hd/yosys.log
docker run --rm \
  -v "$PWD:/work" \
  -w /work \
  -e SKY130HD_LIB="$SKY130HD_LIB" \
  openroad/orfs:latest \
  bash -lc 'source /OpenROAD-flow-scripts/env.sh && openroad -exit scripts/sky130hd/sta.tcl' \
  2>&1 | tee build/sky130hd/sta.log
python3 scripts/sky130hd/summarize.py
cat build/sky130hd/report.md >> "$GITHUB_STEP_SUMMARY"
