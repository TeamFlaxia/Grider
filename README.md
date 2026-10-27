# Grider

Grider is an experimental cellular SIMD processor. It places 16×16-cell compute tiles in a two-dimensional mesh. One instruction is decoded per tile and broadcast to all 256 cells; each cell has its own ALU/MAC, register file, local SRAM, and no instruction decoder.

The repository contains a functional Python emulator, matching tile and mesh RTL, AI-kernel reference examples, and automated Python/RTL comparison. Current milestone tracking is in [TODO.md](TODO.md); the complete v0.1 instruction semantics are in [docs/isa.md](docs/isa.md).

## Architecture

- Each cell has 16 typed 128-bit registers and 16 private 128-bit SRAM words. Each value carries a 4-bit type tag.
- Numeric formats include signed INT4, INT8, INT16, INT32, INT64 and BF16, plus unsigned 128-bit values and predicates.
- The ISA includes arithmetic, bitwise operations, lane selection, private SRAM access, eight-neighbor movement, and row-wise sum/max reductions.
- A 256-bit lane mask selects participants and writers. The 2D tile mesh connects edge values as eight-neighbor halos.
- BF16 add/subtract/multiply/MAC/min/max and row reductions are implemented in Python and RTL. BF16 arithmetic uses round-to-nearest, ties-to-even; INT arithmetic wraps at the selected width.

The RTL has a host/debug port for initializing and reading cell state, but no program fetch unit, compiler, or GEMM microcode generator. Hardware GEMM is scheduled using data movement and repeated MAC instructions. The Python `gemm16` and `grider.kernels.matmul` functions are reference oracles.

## Run examples

Python 3.10+; no third-party packages are required for the emulator or examples.

```sh
python -m grider.examples.vector_add
python -m grider.examples.matmul
python -m grider.examples.softmax
python -m grider.examples.layer_norm
python -m grider.examples.attention
python -m grider.examples.mlp
```

These examples cover dense matmul, stable and causal softmax, layer normalization, single-head scaled dot-product attention, and a two-layer MLP with GELU. They are host-side references, not yet compiler-lowered SIMD programs.

## Verify

Install Icarus Verilog (`iverilog` and `vvp`) to compare Python and RTL:

```sh
python -m unittest discover -s tests -v
python -m grider.verify_rtl
python -m grider.verify_mesh_rtl
```

The tile check compares all 8,192 register/SRAM words across 256 cells after the same instruction stream, including BF16 edge cases and row reductions. The mesh check covers all eight halo directions in a 2×2 mesh. GitHub Actions runs the unit tests, RTL comparisons and examples.

See [docs/architecture.md](docs/architecture.md), [rtl/grider_tile.sv](rtl/grider_tile.sv), and [rtl/grider_mesh.sv](rtl/grider_mesh.sv).
