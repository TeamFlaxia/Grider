<!-- SPDX-License-Identifier: Apache-2.0 -->

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

SRAM22 emits Verilog, Liberty, LEF, GDS, and SPICE views. The timing libraries for this custom size use the generator's interpolated characterization; this run is pre-layout and does not run DRC/LVS or route the macros.

The CI run compares one PE with the default register-file/SRAM arrays mapped to standard cells against the optional SRAM22 path:

| Measurement | Standard-cell fallback | SRAM22 macro path |
|---|---:|---:|
| Standard-cell area | 780,806.36 µm² | 620,223.59 µm² |
| SRAM macro area from LEF | 0 µm² | 532,645.06 µm² |
| Combined standard-cell + macro area | 780,806.36 µm² | 1,152,868.65 µm² |
| Sequential standard-cell instances | 5,477 | 989 |
| Physical SRAM macro instances | 0 | 4 |
| Logical storage bits | 4,224 | 4,224 |
| Physical SRAM capacity | 0 | 17,408 bits |
| Derived pre-layout Fmax | 11.148 MHz | 20.982 MHz |

The macro path's estimated Fmax is about 1.88× the fallback result, and its standard-cell area is lower. With 64-word macros serving 16 logical addresses, it allocates 4.1× the required memory capacity; counting the macro area, total area is about 47.7% higher. This is a speed-versus-area result, not an area reduction. A smaller macro or denser memory configuration would be needed to improve both measures.

## v0.3 dataflow RTL

The v0.3 ISA extensions (opcodes 21–30, F32 elementwise arithmetic, and the
`DOT_ROW`/`TRANSPOSE`/`GATHER`/`SCATTER` datapaths) change the tile area and
timing substantially. The same Sky130HD flow was run for one PE
(`TILE_W=1`, `TILE_H=1`, `LANES=1`) with Yosys 0.52 and the pinned Sky130HD
TT Liberty.

| Measurement | v0.3 | v0.2 |
|---|---:|---:|
| Mapped standard-cell area | 1,460,391.88 µm² | 859,346.68 µm² |
| Mapped standard-cell instances | 269,110 | 146,906 |
| Worst register-to-register slack at 100 ns | -674.9923 ns | 28.0014 ns |
| Derived pre-layout Fmax | 1.290 MHz | 13.889 MHz |

Both columns come from the same local tools (Yosys 0.52) and the same
`abc -script "+strash; dch -f; map"` mapping script, so they are directly
comparable. The v0.3 area is about 70% larger and the worst slack moves from
met to a 0.67 µs violation. The CI flow with Yosys 0.70 measures the same
netlist at 1,480,468.64 µm², 268,375 instances, and -651.7817 ns slack
(1.330 MHz). The earlier v0.2 numbers in this file (780,806.36 µm²,
10.2986 ns slack, 11.148 MHz) were recorded with ABC's default mapping script
and are kept below as the historical baseline.

### ABC mapping script

The default ABC script spends almost all of the mapping time in `dch`, and on
this design it also produces a worse result than the lower-effort variant.
Three mappings of the same v0.3 netlist were compared:

| ABC script | ABC time | Mapped area | Mapped cells | Worst slack | Fmax |
|---|---:|---:|---:|---:|---:|
| default (`dch`) | 3,171 s | 1,224,434.33 µm² | 174,263 | -2,114.2063 ns | 0.452 MHz |
| `+strash; dch -f; map` | 259 s | 1,460,391.88 µm² | 269,110 | -674.9923 ns | 1.290 MHz |
| `+strash; map` | 66 s | 2,322,578.79 µm² | 408,875 | -1,284.3201 ns | 0.674 MHz |

`dch -f` is the operating point the flow now uses: it maps twelve times
faster than the default script, gives the best timing of the three, and costs
about 19% more area. It also keeps the synthesis job inside the CI timeout,
which the default script no longer does for the v0.3 netlist.

### What makes the v0.3 netlist heavy

The pre-map netlist is dominated by multiplexers: 13,884 `$mux` cells out of
17,235 total, against 4,518 out of 5,811 for v0.2. The growth is concentrated
in the main `always_comb` block, where the per-lane type selection gained the
F32 branch and the opcode `case` gained ten new operations. Each of those
branches becomes another 128-bit-wide mux per lane.

Two consequences follow:

- **Synthesis time.** The mux network is what makes ABC slow; the `dch` pass
  alone accounted for 3,171 s of the original run.
- **Critical path.** The worst path runs from `operand_b[0]` to
  `writeback_data_q[0]`: it is the per-lane result computation of the main
  `always_comb` block, which selects between the BF16, F32, and integer
  arithmetic and then between the opcode results, all in one combinational
  pass. The path holds about 5,100 cells, of which about 2,100 are majority
  gates, and several cells carry fanouts of 200 to 740 gates, which
  dominates the delay.

### One-PE flows cannot measure the tile-wide operations

`REDUCE_SUM`, `REDUCE_SUM_COL`, `SCAN_SUM`, `DOT_ROW`, `TRANSPOSE`, and
`GATHER`/`SCATTER` read `operand_a`/`operand_b` across all 256 cells. The
Sky130HD flow elaborates one PE with `LANES=1`, so those array reads fall
outside the declared `[0:LANES-1]` range and the synthesis folds their
datapaths away: the v0.3 pre-map netlist contains only 11 `$mul` cells
against 6 for v0.2, where a live `DOT_ROW` would add hundreds. The numbers
above therefore describe the per-lane datapath only; the tile-wide
operations are not included, and the v0.3 tile is larger and slower than the
table suggests. A separate flow that keeps the tile-wide operations
elaborated is needed before any whole-tile PPA claim can be made.

### SRAM22 macro path (v0.3)

The SRAM22 path was re-run for v0.3 with the same generated 64×128-bit
payload and 64×8-bit tag macros (two of each per PE).

| Measurement | v0.3 macro path | v0.3 standard-cell |
|---|---:|---:|
| Standard-cell area | 1,495,927.21 µm² | 1,460,391.88 µm² |
| SRAM macro area from LEF | 532,645.06 µm² | 0 µm² |
| Combined cell + macro area | 2,028,572.27 µm² | 1,460,391.88 µm² |
| Mapped standard-cell instances | 301,763 | 269,110 |
| Physical SRAM macro instances | 4 | 0 |
| Worst register-to-register slack at 100 ns | -667.6070 ns | -674.9923 ns |
| Derived pre-layout Fmax | 1.303 MHz | 1.290 MHz |

The macro path removes the register-file/SRAM flip-flops (994 sequential
cells against 5,482) and gives a marginally better clock, but the combined
area is about 39% higher than the standard-cell path. The critical path is in
the per-lane arithmetic, not the memory arrays. The CI flow measures the same
macro path at 1,425,507.17 µm² of standard cells plus 532,645.06 µm² of
macro area (1,958,152.23 µm² combined) with -605.0353 ns slack (1.418 MHz).

Pipelining the main `always_comb` block (splitting the decode from the
arithmetic) is required before v0.3 can meet a practical clock; the
per-operation work on `SCAN_SUM` and `DOT_ROW` cannot recover the clock on
its own because those paths are not the worst case in this flow. The
functional RTL, Python model, and RTL co-verification are unaffected: the
v0.3 changes match the Python model for all 8,192 state words.

## Timing and area interpretation

Yosys reports the sum of mapped standard-cell areas. The current netlist contains 5,477 sequential cells, including enabled flip-flops; the earlier count of 4,225 came from the old RTL. The current worst path has 88.3604 ns data arrival and 10.2986 ns slack. The RTL names are hidden in the STA netlist, so this report does not tie that path to a specific source signal.

OpenSTA uses a 100 ns ideal clock, 100 ps clock transition, and zero clock uncertainty. Fmax is calculated as `1000 / (100 ns - worst slack)`. No placed design or extracted SPEF parasitics are supplied, so the reported Fmax values are pre-layout estimates, not routed Fmax. The result covers one PE only; the default 16×16 tile and 2×2 mesh have not been synthesized for area or timing.

The mapping step uses `abc -script "+strash; dch -f; map"`. ABC's default script spends almost all of its time in `dch` on the v0.3 netlist and returns a worse mapping than the lower-effort variant, so the flow pins the explicit script. The measurements above the "Timing and area interpretation" heading were taken with that script.

The flow pins the Sky130HD timing Liberty to PDK repository commit `5a42fd01a0eeb2338340438443c7062e198d97a4` and the OpenROAD Flow container to image digest `sha256:6810dbf0e03dddbc89ed8c0a1e13cad09ce4c98d40c4ac0ab99fdc04b0676347`. The CI artifact contains the reports, Yosys JSON snapshots, and mapped Verilog.

## Architectural implications

The current RTL separates operand reads, execution, and writeback. The Sky130HD flow measures both the standard-cell fallback and the optional SRAM22 macro implementation for one PE. The macro run includes macro area from LEF and macro timing from Liberty; neither run includes placement or routing.

## BF16 microkernel throughput

`rtl/tb_grider_kernel_bench.sv` runs BF16 MOVI, ADD, MUL, and MAC instructions through a one-lane `grider_tile`. Icarus Verilog simulation checks the outputs through the host read port and counts completion cycles. The measured instruction latencies are 4 cycles for ADD/MUL and 5 cycles for MAC. The test executes 16 ADDs, 16 MULs, and 16 MACs; MAC counts as 2 FLOPs (one multiply plus one add).

The Python functional emulator also runs these instruction sequences across all 256 lanes and checks the resulting values. The emulator is not cycle accurate, so its wall-clock time is not used to calculate hardware throughput. The table multiplies the one-lane RTL rate by 256 lanes and assumes the one-PE macro-path Fmax applies to the full tile; this is a projection, not a measured 16×16 tile result.

| BF16 operation | RTL cycles/instruction | 1 lane at 20 MHz | 256 lanes at 20 MHz | 256 lanes at 20.982 MHz* |
|---|---:|---:|---:|---:|
| ADD | 4 | 5 MFLOPS | 1.28 GFLOPS | 1.342848 GFLOPS |
| MUL | 4 | 5 MFLOPS | 1.28 GFLOPS | 1.342848 GFLOPS |
| MAC | 5 | 8 MFLOPS | 2.048 GFLOPS | 2.148557 GFLOPS |

At 20 MHz, the calculation is `lanes × FLOPs per instruction × clock / cycles per instruction`. Since the RTL does not overlap instructions, these rates include the source-read and writeback cycles. The 20.982 MHz column uses the pre-layout Fmax estimate for one PE from the SRAM22 path above; full-tile timing and throughput remain unmeasured.

Run the functional emulator with `python -m grider.benchmark --clock-mhz 20`. The Sky130HD workflow runs the RTL microbenchmark and uploads its cycle-count log with the other synthesis reports.
