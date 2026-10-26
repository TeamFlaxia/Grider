# Resource and timing assessment

## State capacity

Each PE has 16 132-bit registers and 16 132-bit SRAM words, for 4,224 state bits (528 bytes). The default 16×16 tile has 256 PEs:

- Register file: 540,672 bits
- Local SRAM: 540,672 bits
- Total state: 1,081,344 bits (135,168 bytes, or 132 KiB)

The default 2×2 mesh has 4,325,376 state bits (528 KiB). These are exact architectural storage capacities, not synthesized area. A flop implementation needs at least this many state bits, before write muxes, tags, arithmetic, and interconnect.

## Previous RTL baseline (before synchronous memories)

This measurement used the earlier asynchronous-array RTL. The reproducible Sky130HD flow in `scripts/sky130hd/` elaborates `TILE_W=1`, `TILE_H=1`, and `LANES=1`, then maps to the Sky130HD TT library at 25 °C and 1.80 V.

| Measurement | Result |
|---|---:|
| Configuration | 1 PE, 1 lane |
| Mapped standard-cell area | 785,977.56 µm² (0.786 mm²) |
| Mapped standard-cell instances | 106,705 |
| Flip-flop instances | 4,225 |
| Abstract Yosys memories before mapping | 3 × 8-word × 1-bit (24 bits total) |
| SRAM/RAM macro instances after mapping | 0 |
| Worst register-to-register slack at 100 ns | 29.9661 ns |
| Derived pre-layout Fmax | 14.279 MHz |

The mapped flip-flop count matches the 4,224 architectural state bits plus the registered `instruction_done` bit. The earlier register file and local SRAM mapped to flip-flops; no SRAM macro was inferred. The three 8×1-bit abstract memories were small Yosys objects, not the 16×132-bit architectural arrays.

## Current synchronous-memory RTL

The RTL packs the payload and type tag into one word, uses a synchronous read/write port per memory, and keeps reset state in a valid bitmap. A command reads its sources serially, captures the result, and writes back before another command is accepted. This adds instruction latency while separating memory access from arithmetic.

The standard-cell-only Sky130HD flow does not include an SRAM macro Liberty/LEF, so mapped area still includes a flop implementation of each inferred memory. A real macro-level area comparison requires a compatible macro model and physical abstract.

## Timing and area interpretation

Yosys reports the sum of mapped standard-cell areas. The result excludes placement-only cells, clock-tree cells, routing, and physical-design overhead. The mapped netlist contains 4,225 flip-flops and a large combinational arithmetic network. The critical path has 69.9279 ns data arrival and traverses large mux cells followed by a long XOR/majority-cell chain. This is consistent with the register selection and arithmetic datapath; internal signal names are anonymized in the STA netlist, so the report does not identify a specific opcode.

OpenSTA uses a 100 ns ideal clock, 100 ps clock transition, and zero clock uncertainty. Fmax is calculated as `1000 / (100 ns - worst slack)`. No placed design or extracted SPEF parasitics are supplied, so 14.279 MHz is a pre-layout estimate, not routed Fmax. The result covers one PE only; the default 16×16 tile and 2×2 mesh have not been synthesized for area or timing.

The flow pins the Sky130HD timing Liberty to PDK repository commit `5a42fd01a0eeb2338340438443c7062e198d97a4` and the OpenROAD Flow container to image digest `sha256:6810dbf0e03dddbc89ed8c0a1e13cad09ce4c98d40c4ac0ab99fdc04b0676347`. The CI artifact contains the reports, Yosys JSON snapshots, and mapped Verilog.

## Architectural implications

The current RTL now describes each register file and local SRAM as a 16×132 single-port synchronous memory and separates operand reads, execution, and writeback. The Sky130HD flow still maps to a standard-cell Liberty without SRAM macro models, so it can verify abstract memory inference and compare area/Fmax but cannot show the benefit of a physical SRAM macro. The updated flow checks for two 16×132 abstract memories; its post-change report will be attached to the PR Actions run.