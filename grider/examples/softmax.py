"""Run the stable host-side row softmax reference."""
from grider.kernels import softmax_rows


def main() -> None:
    values = [[1.0, 2.0, 3.0], [3.0, 1.0, -1.0]]
    print("Stable softmax:", softmax_rows(values))
    print("Causal softmax:", softmax_rows(values, causal=True))


if __name__ == "__main__":
    main()
