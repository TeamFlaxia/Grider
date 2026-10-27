"""Run a two-layer host reference MLP with GELU."""
from grider.kernels import gelu, matmul


def main() -> None:
    x = [[0.5, -1.0], [1.5, 0.25]]
    w1 = [[1.0, -0.5, 0.25], [0.5, 1.0, -1.0]]
    b1 = [0.1, 0.2, -0.1]
    w2 = [[1.0, 0.5], [-0.5, 1.0], [0.25, -1.0]]
    hidden = matmul(x, w1)
    hidden = [[value + bias for value, bias in zip(row, b1)] for row in hidden]
    activated = gelu(hidden)
    print("Two-layer MLP:", matmul(activated, w2))


if __name__ == "__main__":
    main()
