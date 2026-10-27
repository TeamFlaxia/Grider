"""Execute the prepacked 16x16 BF16 GEMM instruction program."""
from grider.microkernels import run_matmul16_bf16


def main() -> None:
    a = [[float(row == col) for col in range(16)] for row in range(16)]
    b = [[float((row + col) % 4) for col in range(16)] for row in range(16)]
    result = run_matmul16_bf16(a, b)
    print("BF16 16x16 GEMM (first row):", result[0])


if __name__ == "__main__":
    main()
