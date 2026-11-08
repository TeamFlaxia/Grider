# SPDX-License-Identifier: Apache-2.0

"""Dataflow planning helpers for Grider tile kernels.

Tile instructions form a dataflow graph: producers write registers, consumers
read them, and NEIGHBOR / TRANSPOSE / reductions move data between cells.
This module provides small stall-free scheduling utilities used by AI
(matmul/attention/norm) and rendering (raster->shade->blend) pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .sim import Opcode


LATENCY: dict[Opcode, int] = {
    Opcode.NOP: 2,
    Opcode.MOV: 3,
    Opcode.MOVI: 2,
    Opcode.ADD: 4,
    Opcode.SUB: 4,
    Opcode.MUL: 4,
    Opcode.MAC: 5,
    Opcode.AND: 4,
    Opcode.OR: 4,
    Opcode.XOR: 4,
    Opcode.SHL: 4,
    Opcode.SHR: 4,
    Opcode.MIN: 4,
    Opcode.MAX: 4,
    Opcode.SEL: 5,
    Opcode.NEIGHBOR: 3,
    Opcode.LOAD: 3,
    Opcode.STORE: 3,
    Opcode.REDUCE_SUM: 3,
    Opcode.REDUCE_MAX: 3,
    Opcode.CONVERT: 3,
    Opcode.TRANSPOSE: 3,
    Opcode.REDUCE_SUM_COL: 3,
    Opcode.REDUCE_MAX_COL: 3,
    Opcode.SCAN_SUM: 3,
    Opcode.GATHER: 4,
    Opcode.SCATTER: 4,
    Opcode.ROW_BROADCAST: 3,
    Opcode.COL_BROADCAST: 3,
    Opcode.DIV: 4,
    Opcode.DOT_ROW: 4,
}

# Throughput per instruction in FMAs/MACs for tiling estimates.
OPS_PER_INSTRUCTION: dict[Opcode, int] = {
    Opcode.MAC: 2,
    Opcode.DOT_ROW: 16,
    Opcode.ADD: 1,
    Opcode.SUB: 1,
    Opcode.MUL: 1,
}


@dataclass(frozen=True)
class DataflowStage:
    name: str
    opcode: Opcode
    repeat: int = 1


@dataclass(frozen=True)
class PipelineEstimate:
    stage_cycles: tuple[int, ...]
    total_cycles: int
    ops: int
    instruction_count: int


def estimate_pipeline(stages: Sequence[DataflowStage]) -> PipelineEstimate:
    """Estimate serial latency for a dataflow stage list (no overlap)."""
    stage_cycles: list[int] = []
    for stage in stages:
        if stage.repeat < 1:
            raise ValueError("repeat must be positive")
        stage_cycles.append(LATENCY[stage.opcode] * stage.repeat)
    ops = sum(OPS_PER_INSTRUCTION.get(s.opcode, 0) * s.repeat for s in stages)
    return PipelineEstimate(
        tuple(stage_cycles),
        sum(stage_cycles),
        ops,
        sum(s.repeat for s in stages),
    )


def estimate_double_buffered(
    stages: Sequence[DataflowStage],
) -> tuple[int, int]:
    """Estimate depth-2 pipelined latency/throughput for producer/consumer.

    Returns (steady-state cycles per tile, total cycles for one tile batch).
    Overlapping producer stage i with consumer stage i+1 hides all but the
    slowest stage in steady state.
    """
    if not stages:
        raise ValueError("stages must be non-empty")
    per_stage = [LATENCY[s.opcode] * s.repeat for s in stages]
    steady = max(per_stage)
    total = sum(per_stage)
    return (steady, total)


def tile_dataflow_example() -> dict[str, object]:
    """Illustrative tile dataflow: attention score -> scale -> softmax."""
    stages = [
        DataflowStage("qk", Opcode.DOT_ROW, 16),
        DataflowStage("scale", Opcode.MUL, 256),
        DataflowStage("max", Opcode.REDUCE_MAX, 16),
        DataflowStage("sum", Opcode.REDUCE_SUM, 16),
    ]
    est = estimate_pipeline(stages)
    return {
        "stages": stages,
        "estimate": est,
    }
