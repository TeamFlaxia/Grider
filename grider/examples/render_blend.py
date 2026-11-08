# SPDX-License-Identifier: Apache-2.0

"""Alpha blend on a tile: fg*a + bg*(1-a) with F32 elementwise ops."""

from grider import DataType, Instruction, Opcode, Tile
from grider.render import alpha_blend


def main() -> None:
    tile = Tile()
    fg = [1.0] * 256
    bg = [0.0] * 256
    alpha = [0.5] * 256
    tile.load_register(0, fg, DataType.F32)
    tile.load_register(1, bg, DataType.F32)
    tile.load_register(2, alpha, DataType.F32)
    tile.load_register(3, [1.0] * 256, DataType.F32)
    # one_minus_a = 1 - a
    tile.step(Instruction(Opcode.SUB, dst=4, src_a=3, src_b=2, dtype=DataType.F32))
    tile.step(Instruction(Opcode.MUL, dst=5, src_a=0, src_b=2, dtype=DataType.F32))
    tile.step(Instruction(Opcode.MUL, dst=6, src_a=1, src_b=4, dtype=DataType.F32))
    tile.step(Instruction(Opcode.ADD, dst=7, src_a=5, src_b=6, dtype=DataType.F32))
    print("tile blend[0]", tile.read_register(7)[0])
    host = alpha_blend([[1.0] * 4], [[0.0] * 4], [[0.5] * 4])
    print("host blend", host[0][0])


if __name__ == "__main__":
    main()
