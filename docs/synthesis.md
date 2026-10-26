# Resource and timing assessment

## State capacity

Each PE has 16 132-bit registers and 16 132-bit SRAM words, for 4,224 state bits (528 bytes). The default 16×16 tile has 256 PEs:

- Register file: 540,672 bits
- Local SRAM: 540,672 bits
- Total state: 1,081,344 bits (135,168 bytes, or 132 KiB)

The default 2×2 mesh has 4,325,376 state bits (528 KiB). These are exact architectural storage capacities, not synthesized area. A flop implementation needs at least this many state bits, before write muxes, tags, arithmetic, and interconnect.

## Memory inference

Yosys OSS CAD Suite did not finish `proc/opt/memory_collect` for even a 1-PE configuration within the five-minute CI limit. No inferred-memory count or mapped area was obtained.

The RTL's arrays are asynchronously reset element by element and have combinational reads. Each PE also needs multiple register-file read values in the same cycle, including the host/debug read. These patterns make ordinary block RAM inference unlikely; a target-specific synthesis run is needed to confirm the result.

## Timing and area

Integer MUL/MAC operands are sign-extended to 128 bits before multiplication, although the largest supported integer tag is I64. This can create a much wider multiplier than the instruction semantics need.

The likely critical path runs from the register-file read mux through the selected arithmetic path and result/writeback mux to state. No Fmax or physical area can be reported without selecting an FPGA part or ASIC cell library and supplying timing constraints and PVT corner.