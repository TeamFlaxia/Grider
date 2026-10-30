#!/usr/bin/env python3
"""Print logical tile-state and wide-operation costs for 32/64/128-bit payloads."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from grider.widths import standard_width_sweep


def main() -> None:
    print("| Payload bits | Bits/word | State bits/tile | State KiB/tile | 128-bit chunks |")
    print("|---:|---:|---:|---:|---:|")
    for config in standard_width_sweep():
        print(
            f"| {config.payload_width} | {config.bits_per_word} | "
            f"{config.tile_state_bits:,} | {config.tile_state_kib:.1f} | "
            f"{config.wide_operation_chunks} |"
        )
    print("\nThese are logical capacity estimates, not synthesized area or timing.")
    print("The current RTL remains fixed at a 128-bit payload; PPA comparison needs a parameterized tile.")


if __name__ == "__main__":
    main()
