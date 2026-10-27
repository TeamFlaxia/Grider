# Grider

Grider is an experimental cellular SIMD processor. It places 16×16-cell compute tiles in a two-dimensional mesh. One instruction is decoded per tile and broadcast to all 256 cells; each cell has its own ALU/MAC, register file, local SRAM, and no instruction decoder.

The repository contains a functional Python emulator, matching tile and mesh RTL, a host-side assembly language, small instruction-stream kernels, AI-kernel reference examples, and automated Python/RTL comparison. Current milestone tracking is in [TODO.md](TODO.md); the complete v0.1 instruction semantics are in [docs/isa.md](docs/isa.md), and the assembly language and kernel data layouts are in [docs/programming.md](docs/programming.md).

## Architecture

- Each cell has 16 typed 128-bit registers and 16 private 128-bit SRAM words. Each value carries a 4-bit type tag.
- Numeric formats include signed INT4, INT8, INT16, INT32, INT64 and BF16, plus unsigned 128-bit values and predicates.
- The ISA includes arithmetic, bitwise operations, lane selection, private SRAM access, eight-neighbor movement, and row-wise sum/max reductions.
- A 256-bit lane mask selects participants and writers. The 2D tile mesh connects edge values as eight-neighbor halos.
- BF16 add/subtract/multiply/MAC/min/max and row reductions are implemented in Python and RTL. BF16 arithmetic uses round-to-nearest, ties-to-even; INT arithmetic wraps at the selected width.

The `.gr` assembler expands host-submitted instruction streams; it does not emit a binary or add a hardware program fetch unit. `vector_add_bf16`, `row_sum_i32`, and `matmul16_bf16` execute in the functional tile emulator. The 16×16 BF16 GEMM kernel expects its A rows and B columns prepacked by the host. The general Python functions in `grider.kernels` remain higher-precision reference oracles; softmax, layer norm, attention, and MLP are not yet lowered to Grider instructions.

## Run examples

Python 3.10+; no third-party packages are required for the emulator or examples.

```sh
python -m grider.examples.vector_add
python -m grider.examples.row_sum
python -m grider.examples.matmul16_bf16
python -m grider.examples.matmul
python -m grider.examples.softmax
python -m grider.examples.layer_norm
python -m grider.examples.attention
python -m grider.examples.mlp
```

The vector-add and row-sum examples execute assembled Grider instructions. The matmul, stable and causal softmax, layer normalization, single-head scaled dot-product attention, and two-layer MLP examples use Python reference functions.

Run the 16×16 BF16 instruction kernel from Python with `grider.run_matmul16_bf16(a, b)`, where `a` and `b` are 16×16 matrices. Its host packing and BF16 rounding behavior are documented in [docs/programming.md](docs/programming.md).

## Verify

Install Icarus Verilog (`iverilog` and `vvp`) to compare Python and RTL:

```sh
python -m unittest discover -s tests -v
python -m grider.verify_rtl
python -m grider.verify_mesh_rtl
```

The tile check compares all 8,192 register/SRAM words across 256 cells after the same instruction stream, including BF16 edge cases and row reductions. The mesh check covers all eight halo directions in a 2×2 mesh. GitHub Actions runs the unit tests, RTL comparisons and examples.

See [docs/architecture.md](docs/architecture.md), [rtl/grider_tile.sv](rtl/grider_tile.sv), and [rtl/grider_mesh.sv](rtl/grider_mesh.sv).

