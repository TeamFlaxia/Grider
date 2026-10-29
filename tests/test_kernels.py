# SPDX-License-Identifier: Apache-2.0

import math
import unittest

from grider.kernels import layer_norm, matmul, scaled_dot_product_attention, softmax_rows


class KernelReferenceTests(unittest.TestCase):
    def test_matmul(self):
        self.assertEqual(matmul([[1, 2], [3, 4]], [[5, 6], [7, 8]]),
                         [[19.0, 22.0], [43.0, 50.0]])

    def test_softmax_is_stable_and_normalized(self):
        result = softmax_rows([[1000.0, 1001.0, 999.0]])[0]
        self.assertAlmostEqual(math.fsum(result), 1.0)
        self.assertGreater(result[1], result[0])

    def test_causal_softmax_masks_future(self):
        result = softmax_rows([[2, 3, 4], [2, 3, 4], [2, 3, 4]], causal=True)
        self.assertEqual(result[0], [1.0, 0.0, 0.0])
        self.assertEqual(result[1][2], 0.0)
        self.assertAlmostEqual(math.fsum(result[2]), 1.0)

    def test_layer_norm(self):
        result = layer_norm([[1, 2, 3, 4]])[0]
        self.assertAlmostEqual(math.fsum(result), 0.0, places=5)

    def test_attention_shape_and_causality(self):
        q = [[1.0, 0.0], [0.0, 1.0]]
        result = scaled_dot_product_attention(q, q, [[2.0], [4.0]], causal=True)
        self.assertAlmostEqual(result[0][0], 2.0)
        self.assertGreater(result[1][0], 2.0)


if __name__ == "__main__":
    unittest.main()
