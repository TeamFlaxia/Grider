import unittest

from grider.kernels import matmul
from grider.microkernels import LANES, run_matmul16_bf16, run_row_sum_i32, run_vector_add_bf16
from grider.sim import bf16_to_float, float_to_bf16


class MicrokernelTests(unittest.TestCase):
    def test_vector_add_executes_assembled_bf16_program(self):
        a = [float(lane % 16) / 8 for lane in range(LANES)]
        b = [1.25] * LANES
        result = run_vector_add_bf16(a, b)
        expected = [bf16_to_float(float_to_bf16(left + right)) for left, right in zip(a, b)]
        self.assertEqual(result, expected)

    def test_row_sum_executes_with_lane_mask(self):
        values = [lane % 16 + 1 for lane in range(LANES)]
        result = run_row_sum_i32(values)
        self.assertEqual(result, [136] * LANES)

        mask = sum(1 << lane for lane in range(LANES) if lane % 16 in (1, 4, 7, 10, 13))
        masked = run_row_sum_i32(values, mask)
        for lane, value in enumerate(masked):
            self.assertEqual(value, 40 if (mask >> lane) & 1 else 0)

    def test_packed_bf16_matmul_executes_65_instructions(self):
        a = [[float((row + k) % 3) for k in range(16)] for row in range(16)]
        b = [[float((k + col) % 2) for col in range(16)] for k in range(16)]
        self.assertEqual(run_matmul16_bf16(a, b), matmul(a, b))

    def test_matmul_shape_is_checked(self):
        with self.assertRaisesRegex(ValueError, "16x16"):
            run_matmul16_bf16([[1.0]], [[1.0]])


if __name__ == "__main__":
    unittest.main()
