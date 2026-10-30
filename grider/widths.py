"""Logical storage estimates for Grider tile payload-width exploration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TileWidthConfig:
    payload_width: int
    tag_width: int = 4
    tile_width: int = 16
    tile_height: int = 16
    registers_per_lane: int = 16
    sram_words_per_lane: int = 16
    wide_operation_bits: int = 128

    def __post_init__(self) -> None:
        if min(self.payload_width, self.tag_width, self.tile_width,
               self.tile_height, self.registers_per_lane,
               self.sram_words_per_lane, self.wide_operation_bits) < 1:
            raise ValueError("all width and capacity values must be positive")

    @property
    def lane_count(self) -> int:
        return self.tile_width * self.tile_height

    @property
    def words_per_lane(self) -> int:
        return self.registers_per_lane + self.sram_words_per_lane

    @property
    def bits_per_word(self) -> int:
        return self.payload_width + self.tag_width

    @property
    def state_bits_per_lane(self) -> int:
        return self.words_per_lane * self.bits_per_word

    @property
    def tile_state_bits(self) -> int:
        return self.lane_count * self.state_bits_per_lane

    @property
    def tile_state_bytes(self) -> int:
        return (self.tile_state_bits + 7) // 8

    @property
    def wide_operation_chunks(self) -> int:
        return (self.wide_operation_bits + self.payload_width - 1) // self.payload_width

    @property
    def tile_state_kib(self) -> float:
        return self.tile_state_bytes / 1024


def standard_width_sweep() -> tuple[TileWidthConfig, ...]:
    """Return 32-bit and 64-bit alternatives plus the current 128-bit baseline."""
    return tuple(TileWidthConfig(width) for width in (32, 64, 128))
