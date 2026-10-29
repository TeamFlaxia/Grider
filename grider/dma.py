"""Cycle-level burst DMA and ping-pong banked SRAM reference model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DMACounters:
    cycles: int
    dma_cycles: int
    compute_cycles: int
    overlap_cycles: int
    conflict_stalls: int
    words_transferred: int
    bytes_transferred: int

    @property
    def words_per_cycle(self) -> float:
        return self.words_transferred / self.dma_cycles if self.dma_cycles else 0.0


class PingPongTileMemory:
    """Two single-port banks with one word-per-cycle DMA and compute access.

    Computation uses ``active_bank`` while DMA defaults to the other bank.
    Same-bank read/write conflicts are serialized and counted as stalls.
    """

    def __init__(self, words_per_bank: int = 256, *, word_bytes: int = 4) -> None:
        if words_per_bank < 1 or word_bytes < 1:
            raise ValueError("bank depth and word size must be positive")
        self.words_per_bank = words_per_bank
        self.word_bytes = word_bytes
        self._word_mask = (1 << (word_bytes * 8)) - 1
        self.banks: list[list[int]] = [[0] * words_per_bank for _ in range(2)]
        self.active_bank = 0
        self._dma_bank: int | None = None
        self._dma_start = 0
        self._dma_words: tuple[int, ...] = ()
        self._dma_index = 0
        self.cycles = 0
        self.dma_cycles = 0
        self.compute_cycles = 0
        self.overlap_cycles = 0
        self.conflict_stalls = 0
        self.words_transferred = 0

    @property
    def dma_busy(self) -> bool:
        return self._dma_bank is not None

    @property
    def dma_done(self) -> bool:
        return not self.dma_busy

    @property
    def dma_remaining(self) -> int:
        return len(self._dma_words) - self._dma_index

    def start_dma(self, words: Sequence[int], *, start_address: int = 0,
                  bank: int | None = None) -> None:
        if self.dma_busy:
            raise RuntimeError("a DMA burst is already active")
        target = 1 - self.active_bank if bank is None else bank
        if target not in (0, 1):
            raise ValueError("bank must be 0 or 1")
        if start_address < 0 or start_address + len(words) > self.words_per_bank:
            raise ValueError("DMA burst exceeds bank address range")
        if not words:
            raise ValueError("DMA burst must contain at least one word")
        self._dma_bank = target
        self._dma_start = start_address
        self._dma_words = tuple(int(word) & self._word_mask for word in words)
        self._dma_index = 0

    def read_compute(self, address: int) -> int:
        if not 0 <= address < self.words_per_bank:
            raise ValueError("compute address is outside the bank")
        return self.banks[self.active_bank][address]

    def cycle(self, *, compute_active: bool = False,
              compute_address: int | None = None) -> int | None:
        """Advance one cycle; return the active-bank read if requested."""
        self.cycles += 1
        read_value = None
        if compute_active:
            self.compute_cycles += 1
            if compute_address is not None:
                read_value = self.read_compute(compute_address)
        if not self.dma_busy:
            return read_value
        self.dma_cycles += 1
        if compute_active and self._dma_bank == self.active_bank:
            self.conflict_stalls += 1
            return read_value
        index = self._dma_start + self._dma_index
        self.banks[self._dma_bank][index] = self._dma_words[self._dma_index]
        self._dma_index += 1
        self.words_transferred += 1
        if compute_active:
            self.overlap_cycles += 1
        if self._dma_index == len(self._dma_words):
            self._dma_bank = None
            self._dma_words = ()
            self._dma_index = 0
        return read_value

    def swap_buffers(self) -> None:
        if self.dma_busy:
            raise RuntimeError("cannot swap while a DMA burst is active")
        self.active_bank = 1 - self.active_bank

    def counters(self) -> DMACounters:
        return DMACounters(
            cycles=self.cycles,
            dma_cycles=self.dma_cycles,
            compute_cycles=self.compute_cycles,
            overlap_cycles=self.overlap_cycles,
            conflict_stalls=self.conflict_stalls,
            words_transferred=self.words_transferred,
            bytes_transferred=self.words_transferred * self.word_bytes,
        )
