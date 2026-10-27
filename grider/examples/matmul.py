"""Small dense matrix multiplication reference example."""
from grider.kernels import matmul


def main() -> None:
    a = [[float(r + c) for c in range(4)] for r in range(3)]
    b = [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [1.0, 1.0]]
    print("A × B:")
    for row in matmul(a, b):
        print(" ".join(f"{value:6.2f}" for value in row))


if __name__ == "__main__":
    main()
