"""Single-head scaled dot-product attention reference example."""
from grider.kernels import scaled_dot_product_attention


def main() -> None:
    q = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    k = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    v = [[1.0, 0.0], [0.0, 1.0], [2.0, 2.0]]
    result = scaled_dot_product_attention(q, k, v, causal=True)
    print("causal attention output:")
    for row in result:
        print(" ".join(f"{value: .4f}" for value in row))


if __name__ == "__main__":
    main()
