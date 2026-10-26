# Grider architecture

## Organization

Grider is a two-dimensional mesh of tiles. Each tile contains 16×16 = 256 cells and one instruction decoder. The tile decodes once and broadcasts each instruction to its active cells; cells do not fetch or decode instructions independently. The RTL mesh defaults to 2×2 tiles and is parameterized for rectangular arrays.

Each cell owns sixteen 132-bit architectural registers (128-bit payload plus a 4-bit type tag) and sixteen 132-bit private SRAM words. This is a functional prototype capacity, not an area-optimized memory design. The host/debug port initializes cell state and reads it back.

Each instruction has a 256-bit lane mask. Inactive cells hold register and SRAM state. Within-tile neighbor routes are combinational. Tile edges connect through halo buses. An absent neighbor at the outside edge of the mesh returns zero tagged with the source cell's type.

Neighbor direction is N, NE, E, SE, S, SW, W, NW (0–7). Tile and cell indices are row-major. Neighbor operations observe the pre-instruction state and commit all writes together on the active edge.

## Data types and ISA

| Tag | Format | Arithmetic behavior |
| --- | --- | --- |
| `I4` | signed 4-bit integer | wraps modulo 16 |
| `I8` | signed 8-bit integer | wraps modulo 256 |
| `BF16` | bfloat16 | round-to-nearest, ties-to-even |
| `I16`, `I32`, `I64` | signed integer | wraps to selected width |
| `U128` | unsigned 128-bit vector | payload bit operations |
| `PRED` | predicate | low bit, nonzero means true |

Opcodes 0–19 are defined in [ISA v0.1](isa.md). This includes MOV/MOVI, ADD/SUB/MUL/MAC, bitwise operations, shifts, MIN/MAX/SEL, NEIGHBOR, LOAD/STORE and the v0.1 reductions. Reserved opcodes and type tags are no-ops.

BF16 MAC rounds the product to BF16, adds it to the accumulator, then rounds the sum. BF16 row sum rounds at each tree node. BF16 max returns canonical quiet NaN if a participating input is NaN.

## Reduction behavior

`REDUCE_SUM` and `REDUCE_MAX` operate on the 16 columns in each tile row; they do not cross tile boundaries. The reduction uses a balanced binary tree with four combine levels for a 16-cell row: adjacent pairs, then groups of 4, 8 and 16. The lane mask selects both participating values and destination lanes. Each active lane receives the same row result; inactive cells hold their state. A row with no active lanes has no output.

An explicit type selector is applied to every operand and the result. With inherited type, a row uses the `src_a` tag of its leftmost active lane. Integer sums wrap at each tree node. Unsupported numeric type combinations are no-ops.

## Python and RTL contract

`grider.sim.Tile.step` models one tile instruction. `grider.sim.Mesh.step` broadcasts instructions to tiles and snapshots state for cross-tile neighbor reads. `rtl/grider_tile.sv` and `rtl/grider_mesh.sv` implement the matching interfaces.

`python -m grider.verify_rtl` feeds the same instruction stream to both models and compares every register and SRAM payload/tag in one tile. It includes integer and BF16 arithmetic, masking, SRAM, neighbor reads and row reductions. `python -m grider.verify_mesh_rtl` checks all eight halo directions in a 2×2 RTL mesh. The GitHub Actions workflow runs both comparisons.

## Kernel examples and scope

`grider.kernels` contains host reference implementations for matmul, stable row softmax, layer norm, scaled dot-product attention and GELU. Runnable examples include causal attention and a two-layer MLP. They are not yet lowered into SIMD instruction programs.

This prototype has no instruction fetch unit, compiler, GEMM sequencer, performance counters or fault-recovery logic. SRAM timing closure, FPGA resource mapping, ASIC physical design and cycle/area/power comparison remain future work. The Python model is functional, not cycle- or power-accurate.
