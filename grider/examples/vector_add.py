"""Execute a BF16 vector add as a Grider instruction stream."""
from grider.microkernels import LANES, run_vector_add_bf16


def main() -> None:
    a = [lane / 16 for lane in range(LANES)]
    b = [1.5] * LANES
    result = run_vector_add_bf16(a, b)
    print("BF16 vector add (first 8 lanes):", result[:8])


if __name__ == "__main__":
    main()
