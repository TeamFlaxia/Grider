# SPDX-License-Identifier: Apache-2.0

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

    def test_masked_row_reduction_broadcasts_to_active_lanes(self):
        tile = Tile()
        values = [lane % 16 - 8 for lane in range(256)]
        tile.load_register(0, values, DataType.I8)
        mask = sum(1 << lane for lane in range(256) if lane % 16 in (1, 4, 7, 10, 13))
        tile.step(Instruction(Opcode.REDUCE_SUM, dst=1, src_a=0,
                              dtype=DataType.I8, lane_mask=mask))
        result = tile.read_register(1)
        active_cols = (1, 4, 7, 10, 13)
        expected = [sum(values[col] for col in active_cols) if col in active_cols else 0
                    for col in range(16)]
        self.assertEqual([result[lane] for lane in range(16)], expected)

    def test_bf16_row_reduction_uses_tree_rounding(self):
        tile = Tile()
        tile.load_register(0, [1.0] * 256, DataType.BF16)
        tile.step(Instruction(Opcode.REDUCE_SUM, dst=1, src_a=0, dtype=DataType.BF16))
        self.assertEqual(tile.read_register(1), [16.0] * 256)

    def test_reduction_single_active_lane_and_empty_rows(self):
        tile = Tile()
        tile.load_register(0, [lane % 16 - 8 for lane in range(256)], DataType.I8)
        tile.step(Instruction(Opcode.REDUCE_SUM, dst=1, src_a=0,
                              dtype=DataType.I8, lane_mask=1 << 7))
        result = tile.read_register(1)
        self.assertEqual(result[7], -1)
        self.assertEqual(sum(value != 0 for value in result), 1)

    def test_transpose_permutation(self):
        tile = Tile()
        tile.load_register(0, list(range(256)), DataType.I16)
        tile.step(Instruction(Opcode.TRANSPOSE, dst=1, src_a=0, imm=0))
        result = tile.read_register(1)
        self.assertEqual(result[1], 16)
        self.assertEqual(result[16], 1)
        tile.step(Instruction(Opcode.TRANSPOSE, dst=2, src_a=1, imm=0))
        self.assertEqual(tile.read_register(2), list(range(256)))

    def test_rotation_and_flip_permutations(self):
        tile = Tile()
        tile.load_register(0, list(range(256)), DataType.I16)
        tile.step(Instruction(Opcode.TRANSPOSE, dst=1, src_a=0, imm=1))
        self.assertEqual(tile.read_register(1)[0], 15)
        tile.step(Instruction(Opcode.TRANSPOSE, dst=1, src_a=0, imm=6))
        self.assertEqual(tile.read_register(1)[0], 255)

    def test_column_reduction(self):
        tile = Tile()
        tile.load_register(0, list(range(256)), DataType.I16)
        tile.step(Instruction(Opcode.REDUCE_SUM_COL, dst=1, src_a=0, dtype=DataType.I16))
        result = tile.read_register(1)
        self.assertEqual(result[0], sum(row * 16 for row in range(16)))
        self.assertEqual(result[16], result[0])
        tile.step(Instruction(Opcode.REDUCE_MAX_COL, dst=2, src_a=0, dtype=DataType.I16))
        self.assertEqual(tile.read_register(2)[0], 240)

    def test_scan_sum_prefix(self):
        tile = Tile()
        tile.load_register(0, [1] * 256, DataType.I16)
        tile.step(Instruction(Opcode.SCAN_SUM, dst=1, src_a=0, dtype=DataType.I16))
        result = tile.read_register(1)
        self.assertEqual(result[:16], list(range(1, 17)))
        self.assertEqual(result[16], 1)

    def test_dot_row_and_div(self):
        tile = Tile()
        tile.load_register(0, [3] * 256, DataType.I32)
        tile.load_register(1, [4] * 256, DataType.I32)
        tile.step(Instruction(Opcode.DOT_ROW, dst=2, src_a=0, src_b=1, dtype=DataType.I32))
        self.assertEqual(tile.read_register(2)[0], 16 * 12)
        tile.step(Instruction(Opcode.DIV, dst=3, src_a=0, src_b=1, dtype=DataType.I32))
        self.assertEqual(tile.read_register(3)[0], 0)  # 3 // 4 = 0

    def test_gather_scatter_indirect_sram(self):
        tile = Tile()
        tile.load_register(0, list(range(256)), DataType.I16)
        tile.step(Instruction(Opcode.STORE, src_a=0, imm=3))
        tile.load_register(4, [3] * 256, DataType.I16)
        tile.step(Instruction(Opcode.GATHER, dst=6, src_a=4))
        self.assertEqual(tile.read_register(6)[7], 7)
        tile.load_register(2, [99] * 256, DataType.I16)
        tile.load_register(3, [5] * 256, DataType.I16)
        tile.step(Instruction(Opcode.SCATTER, src_a=2, src_b=3))
        self.assertEqual(tile.read_sram(5, 0), 99)

    def test_row_col_broadcast(self):
        tile = Tile()
        tile.load_register(0, [lane % 16 for lane in range(256)], DataType.I16)
        tile.step(Instruction(Opcode.ROW_BROADCAST, dst=1, src_a=0))
        self.assertEqual(tile.read_register(1)[1], 0)
        tile.step(Instruction(Opcode.COL_BROADCAST, dst=2, src_a=0))
        self.assertEqual(tile.read_register(2)[17], 1)

    def test_f32_elementwise_and_mac(self):
        tile = Tile()
        tile.load_register(0, [1.5] * 256, DataType.F32)
        tile.load_register(1, [2.25] * 256, DataType.F32)
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertAlmostEqual(tile.read_register(2)[0], 3.75)
        tile.load_register(3, [1.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.MAC, dst=3, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertAlmostEqual(tile.read_register(3)[0], 1.0 + 1.5 * 2.25)

    def test_f32_add_round_to_nearest_even(self):
        tile = Tile()
        tile.load_register(0, [1.0] * 256, DataType.F32)
        tile.load_register(1, [2.0 ** -24] * 256, DataType.F32)
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x3F800000)
        tile.load_register(1, [3 * 2.0 ** -24] * 256, DataType.F32)
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x3F800002)

    def test_f32_sub_mul_and_mac_bits(self):
        tile = Tile()
        tile.load_register(0, [1.5] * 256, DataType.F32)
        tile.load_register(1, [0.5] * 256, DataType.F32)
        tile.step(Instruction(Opcode.SUB, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x3F800000)
        tile.step(Instruction(Opcode.MUL, dst=3, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(3)[0][0], 0x3F400000)
        tile.load_register(2, [1.0] * 256, DataType.F32)
        tile.load_register(1, [2.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.MAC, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x40800000)

    def test_f32_overflow_and_subnormal(self):
        tile = Tile()
        tile.load_register(0, [3.4e38] * 256, DataType.F32)
        tile.load_register(1, [10.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.MUL, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x7F800000)
        tile.load_register(0, [1e-40] * 256, DataType.F32)
        raw = tile.read_register_raw(0)[0][0]
        tile.step(Instruction(Opcode.ADD, dst=3, src_a=0, src_b=0, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(3)[0][0], (raw * 2) & 0xFFFFFFFF)

    def test_f32_nan_and_min_max(self):
        tile = Tile()
        tile.load_register(0, [float("nan")] * 256, DataType.F32)
        tile.load_register(1, [1.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.ADD, dst=2, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x7FC00000)
        tile.step(Instruction(Opcode.MAX, dst=3, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(3)[0][0], 0x7FC00000)
        tile.load_register(0, [-0.0] * 256, DataType.F32)
        tile.load_register(1, [0.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.MIN, dst=4, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(4)[0][0], 0x80000000)

    def test_f32_reduction_scan_dot(self):
        tile = Tile()
        tile.load_register(0, [1.0] * 256, DataType.F32)
        tile.load_register(1, [2.0] * 256, DataType.F32)
        tile.step(Instruction(Opcode.REDUCE_SUM, dst=2, src_a=0, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(2)[0][0], 0x41800000)
        tile.step(Instruction(Opcode.SCAN_SUM, dst=3, src_a=0, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(3)[15][0], 0x41800000)
        tile.step(Instruction(Opcode.DOT_ROW, dst=4, src_a=0, src_b=1, dtype=DataType.F32))
        self.assertEqual(tile.read_register_raw(4)[0][0], 0x42000000)


if __name__ == "__main__":
    unittest.main()
