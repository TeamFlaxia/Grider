"""Run the host-side FP64 reference matrix multiply."""
from grider.kernels import matmul


def main() -> None:
    a = [[1.0, 2.0], [3.0, 4.0]]
    b = [[5.0, 6.0], [7.0, 8.0]]
    print("Reference matmul:", matmul(a, b))


if __name__ == "__main__":
    main()
