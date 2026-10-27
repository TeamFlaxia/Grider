# Grider assembly and kernels

Grider assembly is a host-side source format for the current instruction stream. `assemble()` turns `.gr` text into the Python `Instruction` records accepted by the emulator. The RTL still has no instruction memory or fetch unit; a future host driver can submit the same records through its instruction interface.

## Syntax

Registers are named `r0` through `r15`. One instruction is written per line, with comma-separated operands. `#`, `;`, and `//` start comments.

| Instruction | Assembly form |
|---|---|
| `NOP` | `nop` |
| `MOV` | `mov rd, ra` |
| `MOVI` | `movi rd, immediate[, type]` |
| Arithmetic and bitwise | `add/sub/mul/mac/and/or/xor/shl/shr/min/max rd, ra, rb[, type]` |
| `SEL` | `sel rd, predicate, true_value, false_value[, type]` |
| `NEIGHBOR` | `neighbor rd, ra, direction` |
| `LOAD` | `load rd, address` |
| `STORE` | `store ra, address` |
| Row reduction | `reduce_sum/reduce_max rd, ra[, type]` |

Type names are `i4`, `i8`, `bf16`, `i16`, `i32`, `i64`, `u128`, and `pred`. The initial type is `i32`. `.dtype bf16` changes the type for following instructions; a type operand overrides it for one instruction. `inherit` (also `auto` or `none`) selects the ISA's type-inheritance behavior.

`.mask all` selects all 256 cells. `.mask <integer-expression>` selects the bits set in a 256-bit lane mask. The mask stays in effect until the next `.mask` directive. Integer expressions allow literals, parentheses, unary `+`, `-`, `~`, and `+`, `-`, `*`, `//`, `%`, shifts, and bitwise operators. Expressions cannot call Python functions or access names.

`.repeat N as index` expands a compile-time block. Write `{index}` where the assembler should substitute `0` through `N-1`:

```asm
.dtype i32
.repeat 4 as k
    movi r0, {k} * 16
.endrepeat
```

There are no labels, branches, macros, or binary encoding in this first version. The assembler caps each repeat at 4,096 iterations and expanded programs at 100,000 instructions. Syntax and operand errors include the source line number.

## Bundled instruction kernels

The bundled programs live under `grider/programs/` and can be loaded with `load_kernel(name)`. `execute(tile, program)` submits the resulting records to a `Tile` emulator.

| Program | Work | Input | Output |
|---|---|---|---|
| `vector_add_bf16` | BF16 add per cell | `r0`, `r1` | `r2` |
| `row_sum_i32` | INT32 sum of each 16-cell row | `r0` | Same sum in active cells of `r2` |
| `matmul16_bf16` | 16×16 BF16 matrix product | Host-prepacked `r0`–`r3` | `r7`, one result per cell |

`run_vector_add_bf16`, `run_row_sum_i32`, and `run_matmul16_bf16` in `grider.microkernels` provide input setup and output collection for these programs. They execute the functional Python tile model. Emulator wall time is not an RTL clock measurement.

### 16×16 BF16 matrix multiply layout

The GEMM program expands to 65 instructions: one accumulator initialization and four instructions for each of the 16 reduction terms (shift amount, two BF16 extracts, and MAC). Each 128-bit packed value stores eight BF16 bit patterns, least-significant element first.

| Register | Value at output cell `(row, column)` |
|---|---|
| `r0` | `A[row, 0:8]` packed |
| `r1` | `A[row, 8:16]` packed |
| `r2` | `B[0:8, column]` packed |
| `r3` | `B[8:16, column]` packed |
| `r4` | Current bit shift, as INT32 |
| `r5`, `r6` | Extracted BF16 elements |
| `r7` | BF16 accumulator and output |

The host repeats each A row across its 16 output columns and each B column across its 16 output rows. The kernel uses the ISA's BF16 `SHR` and `MAC`; intermediate products and accumulations follow the simulator's BF16 rounding. Inputs and results are therefore BF16, not FP32. This layout is a useful emulator kernel and a candidate for host-driver testing; it does not imply that the current RTL can fetch or launch a program on its own.

## Host reference kernels

`grider.kernels` also contains higher-precision Python references for dense matrix multiply, stable and causal softmax, layer normalization, scaled dot-product attention, and GELU. The examples under `grider.examples` show these references alongside the instruction-stream vector add, row sum, and BF16 GEMM. These reference functions are not assembled Grider programs.
