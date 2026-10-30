# Grider v0.2 instruction semantics

This document defines the architectural behavior shared by the Python model and the RTL. Version 0.2 adds FP32 accumulation for BF16 MAC and an explicit BF16/FP32 conversion at opcode 20. Version 0.1 added row reductions at opcodes 18 and 19. The Python `Tile.step` API represents an already accepted instruction; it does not model host-port backpressure timing.

## Encoding and issue

- Opcodes 0 through 20 are defined below. Reserved opcodes 21 through 31 are no-ops.
- Data type tags 0 through 8 are defined. Tag `0xf` means inherit the source type described below; tags 9 through 14 are reserved.
- A reserved opcode or reserved type tag completes as a no-op: registers and SRAM remain unchanged. The RTL still pulses `instruction_done` for a valid/ready issue.
- An instruction is accepted on a rising edge when `rst_n && instruction_valid && instruction_ready`. `instruction_ready` is high only while the tile is idle and no host read or write request is active. It stays low while an accepted instruction is in flight. A mesh broadcasts only when every tile is ready, so a stalled issue has no partial side effects. Keep `instruction_valid` asserted until the accepting edge.
- The RTL latches the instruction at acceptance, then reads operands, executes, and writes back. The single-port register file serializes source reads: no-read instructions take 2 cycles from acceptance to completion; one-read instructions take 3; two-read instructions take 4; three-read instructions take 5. `MAC` and `SEL` use three reads. `MOVI` with an inherited type uses one read.
- `instruction_done` is a one-cycle completion pulse after writeback, not an acceptance pulse. It is high after the edge that commits the instruction and low after the following edge unless another instruction retires. With no host request, `instruction_ready` returns high in the cycle of `instruction_done`, so the next instruction may be accepted on the following rising edge.
- Host writes are accepted on a rising edge when `host_write_enable && host_access_ready`. Host reads use `host_read_enable && host_access_ready`; `host_read_valid` and the data/tag outputs are valid one cycle later. Avoid asserting read and write together; if both are high, the write takes priority.
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
| 20 | `CONVERT` |

## Payload representation

Register and SRAM payloads are 128 bits with a four-bit type tag. Typed scalar payloads are stored canonically with unused high bits zero:

| Type | Stored payload |
| --- | --- |
| I4, I8, I16, I32, I64 | Low 4, 8, 16, 32, or 64 bits |
| BF16 | Low 16 bits |
| PRED | Low bit |
| U128 | All 128 bits |
| F32 | Low 32 bits, IEEE-754 binary32 |

Signed integer arithmetic interprets the selected width as two's complement and wraps modulo that width. BF16 arithmetic rounds to nearest, ties to even. For a BF16 `MAC`, `src_a` and `src_b` are BF16 values and `dst` is the accumulator. The first MAC treats a non-F32 destination as a BF16 accumulator; the result is stored as F32. Later MACs read that F32 accumulator and preserve its precision. Use `CONVERT` with dtype BF16 after the final MAC to round the accumulated value to BF16. NaN results from BF16 MAC are stored as the canonical positive binary32 quiet NaN `0x7fc00000`; NaN sign and payload are not preserved.

## Type selection

For arithmetic and `MOVI`, an explicit tag selects the operation and result type. Tag `0xf` inherits `src_a`'s type, except `SEL`, which inherits `src_b`'s type. Arithmetic operands are interpreted at the selected type even if their stored tags differ. BF16 `MAC` is the exception: its two inputs are BF16, while its destination is interpreted as F32 after the first result has been written.

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
- `CONVERT` converts between BF16 and F32. Its dtype field selects the destination format; the source format comes from the `src_a` type tag. Other source/destination combinations complete as no-ops.
- F32 is an accumulator/result storage format for BF16 MAC. General F32 arithmetic opcodes are not defined in v0.2.
- `REDUCE_SUM` and `REDUCE_MAX` reduce one 16-cell row within a tile. Columns are paired as (0,1), (2,3), and so on, then combined in a balanced tree with strides 2, 4, and 8.
- The lane mask selects both reduction inputs and destination cells. The same row result is written to each active cell in that row; inactive lanes retain their state. A row with no active lanes has no result.
- Integer reductions wrap after each tree node at the selected width. BF16 sum rounds to BF16 at each tree node. BF16 max returns canonical quiet NaN if any active input is NaN. These opcodes support I4, I8, I16, I32, I64, and BF16; other types are no-ops.
- An explicit type selects the reduction format. With inherited type (`0xf`), each row uses the `src_a` type of its leftmost active cell. Reductions do not cross tile boundaries.



## RTL memory and pipeline

Each cell's register file and local SRAM are single-port synchronous memories. Each memory word packs the 128-bit payload and 4-bit type tag together. Reset clears per-word valid bits; an unwritten word reads as zero with the I32 tag without resetting the memory array itself.

An accepted instruction remains the only in-flight instruction until writeback. Operand reads are serialized to use the one memory port, then the result is captured and written back. This pipeline improves timing separation around memory reads and execution, but it does not overlap instructions; throughput is one instruction per several clock cycles. The Python emulator continues to model the architectural operation functionally and does not model this cycle count.

