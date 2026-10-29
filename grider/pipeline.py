"""Latency/throughput model of a ready/valid multiply-accumulate pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineCycle:
    input_ready: bool
    output_valid: bool
    output_value: int | None


class MacPipeline:
    """Three-stage signed MAC model with latency 3 and initiation interval 1."""

    def __init__(self, operand_width: int = 32, result_width: int = 64) -> None:
        if operand_width < 1 or result_width < 1:
            raise ValueError("pipeline widths must be positive")
        self.operand_width = operand_width
        self.result_width = result_width
        self._stages: list[tuple[int, ...] | int | None] = [None, None, None]
        self.cycles = 0
        self.accepted = 0
        self.retired = 0

    @staticmethod
    def _signed(value: int, width: int) -> int:
        value &= (1 << width) - 1
        sign = 1 << (width - 1)
        return value - (1 << width) if value & sign else value

    def cycle(self, *, request: tuple[int, int, int] | None = None,
              output_ready: bool = True) -> PipelineCycle:
        """Run one cycle and optionally submit ``(a, b, accumulator)``.

        The returned valid/value describe the output consumed on this edge.
        If ``input_ready`` is false, the caller must hold its request for a
        later cycle.
        """
        stage0, stage1, stage2 = self._stages
        output_valid = stage2 is not None
        output_value = int(stage2) if output_valid else None
        can_advance_2 = stage2 is None or output_ready
        can_advance_1 = stage1 is None or can_advance_2
        input_ready = stage0 is None or can_advance_1

        next0 = stage0
        next1 = stage1
        next2 = stage2
        if can_advance_2:
            next2 = None if stage1 is None else int(stage1[0]) + int(stage1[1])
        if can_advance_1:
            if stage0 is None:
                next1 = None
            else:
                a, b, accumulator = stage0
                next1 = (a * b, accumulator)
        if input_ready:
            if request is None:
                next0 = None
            else:
                a, b, accumulator = request
                next0 = (
                    self._signed(a, self.operand_width),
                    self._signed(b, self.operand_width),
                    self._signed(accumulator, self.result_width),
                )
                self.accepted += 1

        if output_valid and output_ready:
            self.retired += 1
        if output_value is not None:
            output_value = self._signed(output_value, self.result_width)
        self._stages = [next0, next1, next2]
        self.cycles += 1
        return PipelineCycle(input_ready, output_valid, output_value)

    @property
    def busy(self) -> bool:
        return any(stage is not None for stage in self._stages)
