# Concrete GEMM lowering

`grider.lowering.lower_gemm16` compiles two concrete 16×16 matrices into a
straight-line BF16 ISA program. Each PE maps to one output element. For each
reduction index, row-masked `MOVI` instructions distribute A values, column-
masked `MOVI` instructions distribute B values, and one SIMD `MAC` updates all
outputs. A final `CONVERT` rounds the F32 accumulators to BF16.

`execute_lowered_gemm16` runs the program in the Python tile and reports its
instruction count, documented RTL cycle estimate, and maximum absolute error
against `gemm16`. `python -m grider.verify_gemm_rtl` sends the same generated
instructions through `tb_grider_tile.sv` and compares the RTL output register
with the Python model.

This lowering embeds matrix values in `MOVI` immediates. It demonstrates a
complete reference-to-ISA-to-tile path while the repository has no host-memory
load instruction or program fetch unit. A reusable kernel with runtime matrix
inputs and transfer scheduling remains future work.
