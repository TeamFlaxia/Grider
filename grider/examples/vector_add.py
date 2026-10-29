# SPDX-License-Identifier: Apache-2.0

"""Broadcast a vector add across all 256 cells."""

from grider import DataType, Instruction, Opcode, Tile


def main() -> None:
    tile = Tile()
    lhs = [lane - 128 for lane in range(tile.lane_count)]
    rhs = [3] * tile.lane_count
    tile.load_register(0, lhs, DataType.I8)
    tile.load_register(1, rhs, DataType.I8)
    tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.I8))
    result = tile.read_register(2)
    print(f"cycles: {tile.cycles}")
    print(f"first 8 results: {result[:8]}")


if __name__ == "__main__":
    main()
