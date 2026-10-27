"""Run a small scaled dot-product attention reference."""
from grider.kernels import scaled_dot_product_attention


def main() -> None:
    q = [[1.0, 0.0], [0.0, 1.0]]
    k = [[1.0, 0.0], [0.0, 1.0]]
    v = [[10.0, 1.0], [2.0, 20.0]]
    print("Attention:", scaled_dot_product_attention(q, k, v))
    print("Causal attention:", scaled_dot_product_attention(q, k, v, causal=True))


if __name__ == "__main__":
    main()
