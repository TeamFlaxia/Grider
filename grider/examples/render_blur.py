# SPDX-License-Identifier: Apache-2.0

"""Rendering-style stencil blur on a 16x16 tile using NEIGHBOR + F32 math.

Demonstrates the CA-GPU stencil path: repeated east/south neighbor shifts
accumulate a 2x2 footprint, then F32 elementwise ops divide by 4.
"""

from grider import DataType, Instruction, Opcode, Tile


def blur_tile(values: list[list[float]]) -> Tile:
    tile = Tile()
    flat: list[float] = []
    for row in values:
        flat.extend(row)
    tile.load_register(0, flat, DataType.F32)
    # r1 = east neighbor, r2 = south neighbor, r3 = SE neighbor
    tile.step(Instruction(Opcode.NEIGHBOR, dst=1, src_a=0, imm=2))
    tile.step(Instruction(Opcode.NEIGHBOR, dst=2, src_a=0, imm=4))
    tile.step(Instruction(Opcode.NEIGHBOR, dst=3, src_a=0, imm=3))
    tile.step(Instruction(Opcode.ADD, dst=4, src_a=0, src_b=1, dtype=DataType.F32))
    tile.step(Instruction(Opcode.ADD, dst=5, src_a=2, src_b=3, dtype=DataType.F32))
    tile.step(Instruction(Opcode.ADD, dst=6, src_a=4, src_b=5, dtype=DataType.F32))
    tile.load_register(7, [0.25] * 256, DataType.F32)
    tile.step(Instruction(Opcode.MUL, dst=8, src_a=6, src_b=7, dtype=DataType.F32))
    return tile


def main() -> None:
    image = [[float(r * 16 + c) for c in range(16)] for r in range(16)]
    tile = blur_tile(image)
    result = tile.read_register(8)
    for r in range(4):
        print(" ".join(f"{result[r * 16 + c]:7.1f}" for c in range(8)))


if __name__ == "__main__":
    main()
