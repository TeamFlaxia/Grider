# Grider

Grider is an experimental cellular-array processor: a two-dimensional mesh of compute cells executes one tile-wide SIMD instruction at a time. This repository starts with an executable Python model and a synthesizable SystemVerilog tile prototype.

## First prototype

- A tile contains 16 × 16 = 256 cells.
- The tile has one instruction decoder; every cell executes the decoded operation in lockstep.
- Each cell has 16 typed 128-bit registers (a 4-bit type tag plus a 128-bit payload) and 16 words of private local SRAM.
- Cells can read the previous-cycle value of any of their eight neighbors. Off-tile neighbors read as zero.
- Predication is a 256-bit lane mask. Inactive cells keep their state.
- The Python model supports signed INT4/INT8 arithmetic, BF16 add/multiply, general integer operations, local loads/stores, neighbor reads, MAC, and a 16×16 GEMM reference operation.
- The RTL is an implementation scaffold for the tile-wide issue path, per-cell register/SRAM state, integer ALU/MAC and neighbor reads. BF16 arithmetic and a GEMM instruction are modeled in Python and are follow-on RTL work; GEMM on the hardware maps to a sequence of tile MAC and data-movement instructions.

The architecture deliberately prioritizes local communication. There is no global shared memory in the first model: a host/program loader can initialize cells, while runtime loads and stores target the issuing cell's SRAM.

## Try the Python model

Python 3.10+; no third-party dependencies.

```sh
python -m grider.examples.vector_add
```

Or use the model directly:

```python
from grider import DataType, Instruction, Opcode, Tile

tile = Tile()
tile.load_register(0, [1] * 256, DataType.I8)
tile.load_register(1, [2] * 256, DataType.I8)
tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1))
assert tile.read_register(2)[0] == 3
```

See [docs/architecture.md](docs/architecture.md) for the working contract and [rtl/grider_tile.sv](rtl/grider_tile.sv) for the RTL boundary.

## Status

This is an architectural experiment, not a complete processor implementation. The RTL does not yet include an instruction fetch unit, host interface, mesh router, BF16 datapath, or GEMM sequencer. The Python model is the executable ISA sketch that those pieces can converge on.
