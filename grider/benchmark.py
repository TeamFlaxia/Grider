"""Run small Grider SIMD kernels and estimate throughput from the RTL latency.

The Python tile is functional, not cycle accurate. The cycle counts below come
from the RTL's serialized reads/execute/writeback stages and are checked by the
Sky130 SRAM22 RTL microbenchmark testbench.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from time import perf_counter

from .sim import DataType, Instruction, Opcode, Tile

LANES = 16 * 16
FULL_MASK = (1 << LANES) - 1


@dataclass(frozen=True)
class Case:
    name: str
    opcode: Opcode
    dst: int
    src_a: int
    src_b: int
    dtype: DataType
    cycles_per_instruction: int
    operations_per_lane: int
    is_floating_point: bool
    expected: int | float


CASES = (
    Case("BF16_ADD", Opcode.ADD, 3, 1, 2, DataType.BF16, 4, 1, True, 3.5),
    Case("BF16_MUL", Opcode.MUL, 4, 1, 2, DataType.BF16, 4, 1, True, 3.0),
    Case("BF16_MAC", Opcode.MAC, 0, 1, 2, DataType.BF16, 5, 2, True, 48.5),
    Case("I32_MAC", Opcode.MAC, 5, 6, 6, DataType.I32, 5, 2, False, 151),
)


def _init_tile() -> Tile:
    tile = Tile()
    tile.load_register(0, [0.5] * LANES, DataType.BF16)
    tile.load_register(1, [1.5] * LANES, DataType.BF16)
    tile.load_register(2, [2.0] * LANES, DataType.BF16)
    tile.load_register(5, [7] * LANES, DataType.I32)
    tile.load_register(6, [3] * LANES, DataType.I32)
    return tile


def run_case(tile: Tile, case: Case, iterations: int, active_lanes: int,
             clock_mhz: float) -> dict[str, int | float | str]:
    lane_mask = (1 << active_lanes) - 1
    instruction = Instruction(
        opcode=case.opcode,
        dst=case.dst,
        src_a=case.src_a,
        src_b=case.src_b,
        dtype=case.dtype,
        lane_mask=lane_mask,
    )
    start = perf_counter()
    for _ in range(iterations):
        tile.step(instruction)
    wall_seconds = perf_counter() - start

    values = tile.read_register(case.dst)[:active_lanes]
    if any(value != case.expected for value in values):
        raise RuntimeError(
            f"{case.name} produced {values[:4]!r}; expected {case.expected!r}"
        )

    op_count = iterations * active_lanes * case.operations_per_lane
    rtl_cycles = iterations * case.cycles_per_instruction
    mops = op_count * clock_mhz / rtl_cycles
    return {
        "name": case.name,
        "instructions": iterations,
        "active_lanes": active_lanes,
        "operations": op_count,
        "rtl_cycles": rtl_cycles,
        "cycles_per_instruction": case.cycles_per_instruction,
        "rate_mops": mops,
        "emulator_wall_ms": wall_seconds * 1000,
        "result": case.expected,
        "is_floating_point": case.is_floating_point,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes", type=int, default=LANES,
                        help="number of active SIMD lanes (1..256)")
    parser.add_argument("--iterations", type=int, default=16,
                        help="instructions in each microkernel")
    parser.add_argument("--clock-mhz", type=float, default=20.0,
                        help="assumed hardware clock for the estimate")
    args = parser.parse_args()
    if not 1 <= args.lanes <= LANES:
        parser.error(f"--lanes must be between 1 and {LANES}")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if args.clock_mhz <= 0:
        parser.error("--clock-mhz must be positive")

    tile = _init_tile()
    print(
        f"Grider functional kernel run: {args.lanes}/{LANES} active lanes, "
        f"{args.iterations} instructions/kernel, {args.clock_mhz:.3f} MHz assumed"
    )
    print("Rates use RTL latency: BF16 ADD/MUL=4 cycles, MAC=5 cycles.")
    print("Emulator wall time is functional Python time, not hardware time.")
    for case in CASES:
        result = run_case(tile, case, args.iterations, args.lanes, args.clock_mhz)
        unit = "MFLOPS" if case.is_floating_point else "M integer ops/s"
        rate_giga = result["rate_mops"] / 1000
        rate_text = (
            f"{result['rate_mops']:.3f} {unit}"
            if rate_giga < 1
            else f"{rate_giga:.6f} G{('FLOPS' if case.is_floating_point else 'integer ops/s')}"
        )
        print(
            f"{case.name}: {result['operations']} ops, "
            f"{result['rtl_cycles']} RTL cycles, {rate_text}; "
            f"emulator {result['emulator_wall_ms']:.3f} ms; "
            f"result/lane={result['result']}"
        )


if __name__ == "__main__":
    main()
