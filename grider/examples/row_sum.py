"""Execute a row-wise INT32 reduction as a Grider instruction stream."""
from grider.microkernels import LANES, run_row_sum_i32


def main() -> None:
    values = [lane % 16 + 1 for lane in range(LANES)]
    result = run_row_sum_i32(values)
    print("INT32 row sums (first row):", result[:16])


if __name__ == "__main__":
    main()
