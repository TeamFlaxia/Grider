"""A tiny two-layer MLP forward pass: matmul, bias, GELU, matmul."""
from grider.kernels import gelu, matmul


def main() -> None:
    x = [[0.2, -0.1, 0.5], [1.0, 0.0, -0.5]]
    w1 = [[0.5, -0.2, 0.1, 0.3], [0.1, 0.4, -0.3, 0.2],
          [-0.2, 0.1, 0.6, -0.4]]
    hidden = gelu(matmul(x, w1))
    w2 = [[0.2, -0.1], [0.4, 0.3], [-0.5, 0.2], [0.1, 0.6]]
    output = matmul(hidden, w2)
    print("two-layer MLP output:")
    for row in output:
        print(" ".join(f"{value: .5f}" for value in row))


if __name__ == "__main__":
    main()
