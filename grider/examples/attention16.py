# SPDX-License-Identifier: Apache-2.0

"""Tile QK scoring with DOT_ROW: one query replicated vs 16 keys."""

from grider.lowering import execute_lowered_qk_scores_row16
from grider.kernels import scaled_dot_product_attention


def main() -> None:
    q = [1.0, 0.5, 0.0, -0.5] + [0.25] * 12
    k = [[float(i % 4) - 1.0 for _ in range(16)] for i in range(16)]
    result = execute_lowered_qk_scores_row16(q, k)
    print("instructions:", result.instruction_count)
    print("cycles est:", result.estimated_rtl_cycles)
    print("max err vs Python DOT:", result.max_absolute_error)
    print("scores:", [round(result.output[r][0], 4) for r in range(4)])
    # Host oracle check on a tiny head.
    host = scaled_dot_product_attention([[1.0, 0.0], [0.0, 1.0]],
                                        [[1.0, 0.0], [0.0, 1.0]],
                                        [[2.0], [4.0]], causal=True)
    print("host attention shape", len(host), len(host[0]))


if __name__ == "__main__":
    main()
