# SPDX-License-Identifier: Apache-2.0

"""Layer normalization reference example."""

from grider.kernels import layer_norm


def main() -> None:
    rows = [[0.0, 1.0, 2.0, 3.0], [10.0, 10.0, 10.0, 10.0]]
    for row in layer_norm(rows, scale=[1.0, 1.0, 1.0, 1.0], bias=[0.0] * 4):
        print(" ".join(f"{value: .4f}" for value in row))


if __name__ == "__main__":
    main()
