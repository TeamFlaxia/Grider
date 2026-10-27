"""Run row-wise layer normalization on the host reference."""
from grider.kernels import layer_norm


def main() -> None:
    values = [[1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]]
    print("Layer norm:", layer_norm(values))


if __name__ == "__main__":
    main()
