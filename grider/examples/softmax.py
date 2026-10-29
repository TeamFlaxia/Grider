# SPDX-License-Identifier: Apache-2.0

"""Stable softmax example, including an optional causal mask."""

from grider.kernels import softmax_rows


def main() -> None:
    logits = [[1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]]
    print("softmax:", softmax_rows(logits))
    print("causal:", softmax_rows(logits, causal=True))


if __name__ == "__main__":
    main()
