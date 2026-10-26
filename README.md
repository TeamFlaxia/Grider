# Grider

Grider is an experimental cellular SIMD processor. It places 16×16-cell compute tiles in a two-dimensional mesh. One instruction is decoded per tile and broadcast to all 256 cells; each cell has its own ALU/MAC, register file, local SRAM, and no instruction decoder.

The repository now contains a functional Python emulator, matching tile and mesh RTL, common AI-kernel reference examples, and automated Python/RTL comparison.

## Architecture

- Each cell has 16 typed 128-bit registers and 16 private 128-bit SRAM words. Each register or SRAM word carries a 4-bit type tag.
- Supported numeric tags include signed INT4, INT8, INT16, INT32, INT64 and BF16, plus unsigned 128-bit bit vectors and predicates.
- The instruction set includes MOV/MOVI, ADD/SUB/MUL/MAC, bitwise operations, shifts, MIN/MAX/SEL, local LOAD/STORE and 8-neighbor reads.
- `SEL` uses three source registers: `src_a` is the predicate, `src_b` is selected when true, and `src_c` when false.
- A 256-bit lane mask keeps inactive cells unchanged.
- The 2D mesh broadcasts instructions to every tile and connects tile-edge values as synchronous 8-neighbor halos. Mesh-edge reads return zero.
- BF16 add/subtract/multiply/MAC/min/max are implemented in both Python and RTL with round-to-nearest, ties-to-even. INT4/INT8 arithmetic wraps at the selected width.

The hardware includes an external host/debug port for initializing and reading cell state. It does not include a program fetch unit, compiler, or GEMM microcode generator. Matrix multiplication in hardware is scheduled as data movement plus repeated MAC instructions; the Python `gemm16` and `grider.kernels.matmul` functions are reference oracles.

## Run examples

Python 3.10+; no third-party packages are needed for the emulator or kernel examples.

```sh
python -m grider.examples.vector_add
python -m grider.examples.matmul
python -m grider.examples.softmax
python -m grider.examples.layer_norm
python -m grider.examples.attention
python -m grider.examples.mlp
```

The AI examples cover dense matmul, stable and causal softmax, layer normalization, single-head scaled dot-product attention, and a two-layer MLP with GELU. They are clear host-side reference kernels, not yet compiler-lowered SIMD programs.

## Verify

Install Icarus Verilog (`iverilog` and `vvp`) to compare the emulator and RTL:

```sh
python -m unittest discover -s tests -v
python -m grider.verify_rtl
python -m grider.verify_mesh_rtl
```

The tile comparison feeds the same instruction stream to Python and RTL, then compares all 8,192 register/SRAM words across 256 cells. It covers integer operations, BF16 edge and random finite cases, masking, local memory and neighbors. The mesh comparison checks all eight halo directions across four tiles. GitHub Actions runs both comparisons and all examples on pushes and pull requests.

See [docs/architecture.md](docs/architecture.md), [rtl/grider_tile.sv](rtl/grider_tile.sv), and [rtl/grider_mesh.sv](rtl/grider_mesh.sv).
