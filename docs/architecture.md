# Grider architecture

## Organization

The Grider machine is a two-dimensional mesh of tiles. A tile has 16×16 = 256 cells and one instruction decoder. It decodes once and broadcasts the operation to all active cells; cells do not fetch or decode instructions independently. The RTL mesh defaults to 2×2 tiles and is parameterized for larger rectangular arrays.

Each cell owns a 16×132-bit register file and a 16×132-bit local SRAM. Each is described as a single-port synchronous memory; payload and type tag share one 132-bit word. A small valid bitmap supplies the architectural reset value, so the memory words themselves do not need reset circuitry. The host/debug port initializes words and reads them back through a one-cycle request/valid handshake.

The lane mask has one bit per cell. Inactive lanes hold both register and SRAM state. A neighbor instruction reads a pre-instruction snapshot; all cells and tiles commit their writes together in the writeback stage. Within-tile routes are combinational. At tile boundaries, the selected source values are sent through halo buses after the synchronous register read. At the outer boundary of the mesh, a missing neighbor reads as zero with the source type tag.

Neighbor direction encoding is N, NE, E, SE, S, SW, W, NW (0–7). Tile coordinates are row-major in the software mesh model; cell coordinates are row-major within each tile.

## Data formats

| Tag | Format | Arithmetic behavior |
| --- | --- | --- |
| `I4` | signed 4-bit integer | wraps modulo 16; interpreted as signed on reads |
| `I8` | signed 8-bit integer | wraps modulo 256; interpreted as signed on reads |
| `BF16` | bfloat16 | add, subtract, multiply, MAC, min and max; round-to-nearest, ties-to-even |
| `I16`, `I32`, `I64` | signed integers | wrap to the selected width |
| `U128` | unsigned 128-bit vector | bit operations and payload movement |
| `PRED` | predicate | nonzero means true |

BF16 MAC rounds the product to BF16 and then rounds the accumulated sum to BF16. The standalone `gemm16` reference instead accumulates in host float and rounds once at the output; use the instruction emulator when matching hardware BF16 accumulation behavior.

## Instruction sketch

| Operation | Behavior |
| --- | --- |
| `MOV`, `MOVI` | copy a typed value or load an immediate |
| `ADD`, `SUB`, `MUL`, `MAC` | lane-wise numeric arithmetic; MAC adds product to old `dst` |
| `AND`, `OR`, `XOR`, `SHL`, `SHR` | payload bit operations |
| `MIN`, `MAX` | signed integer or BF16 comparison |
| `SEL` | `dst = src_a != 0 ? src_b : src_c` |
| `NEIGHBOR` | copy one of eight adjacent cell values |
| `LOAD`, `STORE` | read/write one word of each active cell's local SRAM |

An instruction carries `opcode`, destination/source register indices, a 128-bit immediate, a type selector, and a 256-bit lane mask. The type selector `0xf` inherits `src_a`'s type, or `src_b` for `SEL`. The complete type, reserved-encoding, immediate, and operation rules are in [docs/isa.md](isa.md). `LOAD`/`STORE` use `imm[3:0]`; `NEIGHBOR` uses `imm[2:0]`.

## Python and RTL contract

`grider.sim.Tile.step` models one tile instruction. `grider.sim.Mesh.step` broadcasts one instruction to a rectangular mesh and snapshots values for cross-tile neighbor reads. The RTL equivalent is `grider_tile` plus the `grider_mesh` wrapper. Both expose host/debug state access in hardware; the Python model uses `load_register`, `load_sram`, and read methods.

`python -m grider.verify_rtl` initializes a tile through the host port, issues the same integer and BF16 instruction stream to both models, and compares every register and SRAM payload and tag. `python -m grider.verify_mesh_rtl` compares every register in a 2×2 RTL mesh after testing all eight halo directions. The RTL testbenches also check the host read-valid handshake, busy/ready behavior, delayed completion, and atomic mesh issue. The GitHub Actions workflow runs those checks.

## AI kernel examples and current scope

`grider.kernels` contains dependency-free host reference implementations for matmul, row softmax, layer norm, scaled dot-product attention, and GELU. `grider.examples` provides runnable demonstrations, including a tiny two-layer MLP. These reference kernels are not yet lowered to Grider instruction programs. The tile ISA has the arithmetic and local communication building blocks; a tiled GEMM mapping, multi-head batching, compiler, instruction fetch, and host runtime remain follow-on work.

The Python model is functional rather than cycle-, area-, or power-accurate. The RTL uses synchronous single-port memories and processes one instruction at a time through operand-read, execute, and writeback stages. Multi-source operands are read in separate cycles, so instructions do not overlap and latency depends on the number of reads. This stage structure shortens the memory-to-arithmetic path; it does not yet provide one-instruction-per-cycle throughput. SRAM macro mapping, banking, deeper arithmetic pipelines, mesh links between physically separate chips, exceptions, and cache coherence remain follow-on work.
