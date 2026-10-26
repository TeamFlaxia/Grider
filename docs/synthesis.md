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

The RTL packs the payload and type tag into one word, uses a synchronous read/write port per memory, and keeps reset state in a valid bitmap. A command reads its sources, executes, and writes back before another command is accepted. Reads, execution, and writeback occupy separate stages, but the stages do not overlap different instructions.

The Sky130HD run checked one PE (`TILE_W=1`, `TILE_H=1`, `LANES=1`) and found two abstract 16×132 memories for the register file and local SRAM. Six small one-bit memories also remain for control state. The default standard-cell path expands the two arrays into standard cells. A separate `GRIDER_USE_SRAM22` path instantiates generated payload and tag macros, and supplies their Liberty and LEF views to synthesis and timing analysis.

| Measurement | Current staged RTL | Earlier RTL |
|---|---:|---:|
| Mapped standard-cell area | 780,806.36 µm² | 785,977.56 µm² |
| Standard-cell instances | 104,691 | 106,705 |
| Sequential-cell instances | 5,477 | 4,225 |
| Abstract 16×132 memories | 2 | 0 |
| SRAM/RAM macro instances | 0 | 0 |
| Worst slack at a 100 ns clock | 10.2986 ns | 29.9661 ns |
| Derived pre-layout Fmax | 11.148 MHz | 14.279 MHz |

The area fell by about 0.7%, while the estimated Fmax fell by about 22%. The standard-cell fallback confirms abstract memory inference, but the wide RTL read mux remains in the mapped logic. The SRAM22 path below uses hard macros to remove that array mux from the standard-cell datapath.

## SRAM22 macro path

The Sky130 flow generates a `64×128` payload macro and a `64×8` tag macro for each logical memory. The 16 architectural addresses use the first 16 rows; the extra depth is the smallest SRAM22 timing configuration. The valid bitmap remains in standard cells so reset does not clear the physical SRAM. This gives four hard macros per PE: two for the register file and two for local SRAM.

SRAM22 emits Verilog, Liberty, LEF, GDS, and SPICE views. The timing libraries for this custom size use the generator's interpolated characterization; this run is pre-layout and does not run DRC/LVS or route the macros. Treat the macro timing as an integration estimate until physical verification is added.

## Timing and area interpretation

Yosys reports the sum of mapped standard-cell areas. The current netlist contains 5,477 sequential cells, including enabled flip-flops; the earlier count of 4,225 came from the old RTL. The current worst path has 88.3604 ns data arrival and 10.2986 ns slack. The RTL names are hidden in the STA netlist, so this report does not tie that path to a specific source signal.

OpenSTA uses a 100 ns ideal clock, 100 ps clock transition, and zero clock uncertainty. Fmax is calculated as `1000 / (100 ns - worst slack)`. No placed design or extracted SPEF parasitics are supplied, so 11.148 MHz is a pre-layout estimate, not routed Fmax. The result covers one PE only; the default 16×16 tile and 2×2 mesh have not been synthesized for area or timing.

The flow pins the Sky130HD timing Liberty to PDK repository commit `5a42fd01a0eeb2338340438443c7062e198d97a4` and the OpenROAD Flow container to image digest `sha256:6810dbf0e03dddbc89ed8c0a1e13cad09ce4c98d40c4ac0ab99fdc04b0676347`. The CI artifact contains the reports, Yosys JSON snapshots, and mapped Verilog.

## Architectural implications

The current RTL separates operand reads, execution, and writeback. The Sky130HD flow measures both the standard-cell fallback and the optional SRAM22 macro implementation for one PE. The macro run includes macro area from LEF and macro timing from Liberty; neither run includes placement or routing.
