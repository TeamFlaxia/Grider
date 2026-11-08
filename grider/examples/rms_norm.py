# SPDX-License-Identifier: Apache-2.0

"""RMSNorm reference example plus tile mean-square via REDUCE_SUM."""

from grider import DataType, Instruction, Opcode, Tile
from grider.kernels import rms_norm


def tile_mean_square(row: list[float]) -> float:
    tile = Tile()
    values = row + [0.0] * (256 - len(row))
    tile.load_register(0, values, DataType.F32)
    tile.step(Instruction(Opcode.MUL, dst=1, src_a=0, src_b=0, dtype=DataType.F32))
    tile.step(Instruction(Opcode.REDUCE_SUM, dst=2, src_a=1, dtype=DataType.F32))
    return float(tile.read_register(2)[0])


def main() -> None:
    x = [[1.0, 2.0, 3.0, 4.0]]
    print("rms_norm:", rms_norm(x))
    print("tile row mean-square (16-wide):", tile_mean_square([1.0, 2.0, 3.0, 4.0][:16]))


if __name__ == "__main__":
    main()
