import unittest

from grider import DataType, Instruction, Mesh, Opcode, Tile
from grider.sim import bf16_to_float, float_to_bf16


class TileEmulatorTests(unittest.TestCase):
    def test_i4_arithmetic_wraps(self):
        tile = Tile()
        tile.load_register(0, [7] * 256, DataType.I4)
        tile.load_register(1, [1] * 256, DataType.I4)
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.I4))
        self.assertEqual(tile.read_register(2), [-8] * 256)

    def test_lane_mask_preserves_inactive_cells(self):
        tile = Tile()
        tile.load_register(0, [5] * 256, DataType.I8)
        tile.load_register(1, [2] * 256, DataType.I8)
        mask = sum(1 << lane for lane in range(0, 256, 2))
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1,
                              dtype=DataType.I8, lane_mask=mask))
        self.assertEqual(tile.read_register(2)[::2], [7] * 128)
        self.assertEqual(tile.read_register(2)[1::2], [0] * 128)

    def test_neighbor_reads_pre_instruction_state(self):
        tile = Tile()
        values = list(range(256))
        tile.load_register(0, values, DataType.I16)
        tile.step(Instruction(Opcode.NEIGHBOR, dst=0, src_a=0, imm=2))  # east, in place
        result = tile.read_register(0)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[15], 0)
        self.assertEqual(result[16], 17)

    def test_local_sram_round_trip(self):
        tile = Tile()
        tile.load_register(0, [lane - 128 for lane in range(256)], DataType.I8)
        tile.step(Instruction(Opcode.STORE, src_a=0, imm=3))
        tile.step(Instruction(Opcode.LOAD, dst=1, imm=3))
        self.assertEqual(tile.read_register(1), tile.read_register(0))

    def test_predicate_decodes_as_zero_or_one(self):
        tile = Tile()
        tile.load_register(0, [lane % 2 for lane in range(256)], DataType.PRED)
        self.assertEqual(tile.read_register(0), [lane % 2 for lane in range(256)])

    def test_bf16_ties_to_even(self):
        self.assertEqual(float_to_bf16(1.0), 0x3F80)
        self.assertEqual(bf16_to_float(float_to_bf16(1.0)), 1.0)
        self.assertEqual(float_to_bf16(1.0 + 2 ** -8), 0x3F80)
        self.assertEqual(float_to_bf16(1.0 + 3 * 2 ** -8), 0x3F82)

    def test_mesh_neighbor_crosses_tile_boundary_synchronously(self):
        mesh = Mesh(tiles_x=2, tiles_y=1)
        west = mesh.tile_at(0, 0)
        east = mesh.tile_at(1, 0)
        west.load_register(0, list(range(256)), DataType.I16)
        east.load_register(0, [1000 + lane for lane in range(256)], DataType.I16)
        mesh.step(Instruction(Opcode.NEIGHBOR, dst=0, src_a=0, imm=2))
        result_west = west.read_register(0)
        result_east = east.read_register(0)
        self.assertEqual(result_west[15], 1000)
        self.assertEqual(result_west[31], 1016)
        self.assertEqual(result_east[255], 0)


if __name__ == "__main__":
    unittest.main()
