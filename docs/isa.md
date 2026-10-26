# Grider v0.1 instruction semantics

This document defines the architectural behavior shared by the Python model and the RTL. Version 0.1 adds row reductions at opcodes 18 and 19; all other v0 encodings retain their behavior. The Python `Tile.step` API represents an already accepted instruction; it does not model host-port backpressure timing.

## Encoding and issue

- Opcodes 0 through 19 are defined below. Reserved opcodes 20 through 31 are no-ops.
- Data type tags 0 through 7 are defined. Tag `0xf` means inherit the source type described below; tags 8 through 14 are reserved.
- A reserved opcode or reserved type tag completes as a no-op: registers and SRAM remain unchanged. The RTL still pulses `instruction_done` for a valid/ready issue.
- An instruction is accepted on a rising edge when `instruction_valid && instruction_ready`. While a host write owns the tile state port, `instruction_ready` is low. Keep `instruction_valid` asserted until the instruction is accepted.
- Inactive lanes preserve their register and SRAM state.

| Opcode | Mnemonic |
| ---: | --- |
| 0 | `NOP` |
| 1 | `MOV` |
| 2 | `MOVI` |
| 3 | `ADD` |
| 4 | `SUB` |
| 5 | `MUL` |
| 6 | `MAC` |
| 7 | `AND` |
| 8 | `OR` |
| 9 | `XOR` |
| 10 | `SHL` |
| 11 | `SHR` |
| 12 | `MIN` |
| 13 | `MAX` |
| 14 | `SEL` |
| 15 | `NEIGHBOR` |
| 16 | `LOAD` |
| 17 | `STORE` |
| 18 | `REDUCE_SUM` |
| 19 | `REDUCE_MAX` |

## Payload representation

Register and SRAM payloads are 128 bits with a four-bit type tag. Typed scalar payloads are stored canonically with unused high bits zero:

| Type | Stored payload |
| --- | --- |
| I4, I8, I16, I32, I64 | Low 4, 8, 16, 32, or 64 bits |
| BF16 | Low 16 bits |
| PRED | Low bit |
| U128 | All 128 bits |

Signed integer arithmetic interprets the selected width as two's complement and wraps modulo that width. BF16 arithmetic rounds to nearest, ties to even. BF16 MAC rounds the product to BF16 before adding it to the accumulator, then rounds the sum.

## Type selection

For arithmetic and `MOVI`, an explicit tag selects the operation and result type. Tag `0xf` inherits `src_a`'s type, except `SEL`, which inherits `src_b`'s type. Both arithmetic operands and the MAC accumulator are interpreted at that selected type, even if their stored tags differ.

`MOV` copies `src_a` and preserves its tag; its type field is ignored. `SEL` tests whether the raw `src_a` payload is nonzero, then copies the selected `src_b` or `src_c` payload into the result type. The selected payload is reinterpreted and truncated to that type; it is not numerically converted.

`NEIGHBOR`, `LOAD`, and `STORE` preserve the source or stored type tag and ignore the type field. A missing mesh neighbor returns zero with the current lane's `src_a` tag.

## Defined operations

- `ADD`, `SUB`, `MUL`, `MAC`, `MIN`, and `MAX` are defined for I4, I8, I16, I32, I64, and BF16. Using U128 or PRED with these operations is a no-op.
- `AND`, `OR`, `XOR`, `SHL`, and `SHR` operate on payload bits for all defined types. Results are normalized to the selected type.
- Shift counts use the low seven bits of the raw `src_b` payload. `SHR` is arithmetic for signed integer types and logical for BF16, U128, and PRED.
- `SEL` uses `src_a` as a nonzero predicate, `src_b` as the true value, and `src_c` as the false value.
- `NEIGHBOR` uses `imm[2:0]` as N, NE, E, SE, S, SW, W, NW (0–7). Higher immediate bits are ignored.
- `LOAD` and `STORE` use `imm[3:0]` as the local SRAM address. Higher immediate bits are ignored.
- `MOVI` uses the immediate's low bits and normalizes them to the selected type.
- `REDUCE_SUM` and `REDUCE_MAX` reduce one 16-cell row within a tile. Columns are paired as (0,1), (2,3), and so on, then combined in a balanced tree with strides 2, 4, and 8.
- The lane mask selects both reduction inputs and destination cells. The same row result is written to each active cell in that row; inactive lanes retain their state. A row with no active lanes has no result.
- Integer reductions wrap after each tree node at the selected width. BF16 sum rounds to BF16 at each tree node. BF16 max returns canonical quiet NaN if any active input is NaN. These opcodes support I4, I8, I16, I32, I64, and BF16; other types are no-ops.
- An explicit type selects the reduction format. With inherited type (`0xf`), each row uses the `src_a` type of its leftmost active cell. Reductions do not cross tile boundaries.


