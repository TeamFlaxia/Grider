# SPDX-License-Identifier: Apache-2.0

import math
import unittest

from grider.dataflow import estimate_double_buffered, estimate_pipeline, LATENCY
from grider.kernels import conv2d, histogram_rows, rms_norm, rope, silu, swiglu_gate, topk_rows
from grider.lowering import execute_lowered_qk_scores_row16, execute_lowered_transpose16
from grider.render import alpha_blend, barycentric, bilinear_sample, box_blur, lambert, sobel_edge
from grider.sim import Opcode


class KernelExtensionTests(unittest.TestCase):
    def test_rms_norm_zero_mean_square(self):
        result = rms_norm([[0.0, 0.0, 0.0, 0.0]])
        self.assertEqual(result, [[0.0, 0.0, 0.0, 0.0]])

    def test_rms_norm_known(self):
        result = rms_norm([[3.0, 4.0]])
        inv = 1.0 / math.sqrt((9.0 + 16.0) / 2.0 + 1e-6)
        self.assertAlmostEqual(result[0][0], 3.0 * inv)
        self.assertAlmostEqual(result[0][1], 4.0 * inv)

    def test_silu_and_swiglu(self):
        self.assertAlmostEqual(silu([[0.0]])[0][0], 0.0)
        out = swiglu_gate([[1.0]], [[2.0]])
        self.assertAlmostEqual(out[0][0], 2.0 / (1.0 + math.exp(-1.0)))

    def test_rope_zero_position_is_identity(self):
        x = [[1.0, 2.0, 3.0, 4.0]]
        self.assertEqual(rope(x, positions=[0]), x)

    def test_conv2d_identity(self):
        kernel = [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]]
        x = [[1.0, 2.0], [3.0, 4.0]]
        self.assertEqual(conv2d(x, kernel), [[1.0, 2.0], [3.0, 4.0]])

    def test_histogram_and_topk(self):
        self.assertEqual(histogram_rows([[0.0, 1.0, 1.0]], 2), [[1, 2]])
        self.assertEqual(topk_rows([[1.0, 3.0, 2.0]], 2), [[3.0, 2.0]])


class RenderTests(unittest.TestCase):
    def test_box_blur_uniform(self):
        self.assertEqual(box_blur([[2.0, 2.0], [2.0, 2.0]]), [[2.0, 2.0], [2.0, 2.0]])

    def test_sobel_flat_is_zero(self):
        result = sobel_edge([[1.0] * 3 for _ in range(3)])
        self.assertEqual(result[1][1], 0.0)

    def test_bilinear_center(self):
        tex = [[0.0, 1.0], [0.0, 1.0]]
        self.assertAlmostEqual(bilinear_sample(tex, 0.25, 0.25), 0.0, places=5)

    def test_alpha_blend(self):
        out = alpha_blend([[1.0]], [[0.0]], [[0.25]])
        self.assertAlmostEqual(out[0][0], 0.25)

    def test_barycentric_and_lambert(self):
        w = barycentric(0.5, 0.5, (0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        self.assertIsNotNone(w)
        self.assertAlmostEqual(sum(w), 1.0)
        self.assertAlmostEqual(lambert((0.0, 0.0, 1.0), (0.0, 0.0, 1.0), 0.5), 0.5)


class LoweringDataflowTests(unittest.TestCase):
    def test_transpose_lowering(self):
        a = [[float(r * 16 + c) for c in range(16)] for r in range(16)]
        result = execute_lowered_transpose16(a)
        self.assertEqual(result.max_absolute_error, 0.0)
        self.assertEqual(result.output[0][1], float(a[1][0]))

    def test_qk_scores(self):
        q = [1.0] * 16
        k = [[2.0] * 16 for _ in range(16)]
        result = execute_lowered_qk_scores_row16(q, k)
        self.assertEqual(result.max_absolute_error, 0.0)
        self.assertAlmostEqual(result.output[0][0], 32.0)

    def test_pipeline_estimate(self):
        est = estimate_pipeline([])
        self.assertEqual(est.total_cycles, 0)
        self.assertEqual(LATENCY[Opcode.DOT_ROW], 4)
        steady, total = estimate_double_buffered(
            [__import__("grider.dataflow", fromlist=["DataflowStage"]).DataflowStage("a", Opcode.MAC, 1)]
        )
        self.assertEqual(steady, 5)
        self.assertEqual(total, 5)


if __name__ == "__main__":
    unittest.main()
