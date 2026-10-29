"""Epoch-tagged, double-buffered state for asynchronous tile updates.

This module is a reference protocol model. A tile stages a complete next-state
image, publishes its epoch, and swaps only after every in-mesh Moore neighbor
has published the same epoch.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Generic, TypeVar


State = TypeVar("State")
_MOORE = ((0, -1), (1, -1), (1, 0), (1, 1),
          (0, 1), (-1, 1), (-1, 0), (-1, -1))


class EpochBuffer(Generic[State]):
    """One tile's front/back state images and publication epoch."""

    def __init__(self, initial_state: State, *, epoch: int = 0,
                 epoch_bits: int = 32) -> None:
        if epoch_bits < 1:
            raise ValueError("epoch_bits must be positive")
        self.epoch_bits = epoch_bits
        self._mask = (1 << epoch_bits) - 1
        self._current_state = deepcopy(initial_state)
        self.current_epoch = epoch & self._mask
        self._next_state: State | None = None
        self._next_epoch: int | None = None

    @property
    def current_state(self) -> State:
        return deepcopy(self._current_state)

    @property
    def next_state(self) -> State | None:
        return deepcopy(self._next_state)

    @property
    def published_epoch(self) -> int:
        return self.current_epoch if self._next_epoch is None else self._next_epoch

    @property
    def pending(self) -> bool:
        return self._next_epoch is not None

    def publish(self, next_state: State, epoch: int) -> None:
        """Stage a complete next-state image for exactly the next epoch."""
        if self.pending:
            raise RuntimeError("a next-state image is already pending")
        epoch &= self._mask
        expected = (self.current_epoch + 1) & self._mask
        if epoch != expected:
            raise ValueError(f"expected epoch {expected}, got {epoch}")
        self._next_state = deepcopy(next_state)
        self._next_epoch = epoch

    def ready_to_swap(self, neighbor_epochs: list[int] | tuple[int, ...]) -> bool:
        return self.pending and all((epoch & self._mask) == self._next_epoch
                                    for epoch in neighbor_epochs)

    def swap(self, neighbor_epochs: list[int] | tuple[int, ...]) -> bool:
        """Promote the staged image if every supplied neighbor is in epoch."""
        if not self.ready_to_swap(neighbor_epochs):
            return False
        assert self._next_state is not None and self._next_epoch is not None
        self._current_state = self._next_state
        self.current_epoch = self._next_epoch
        self._next_state = None
        self._next_epoch = None
        return True


class EpochMesh(Generic[State]):
    """Moore-neighbor epoch coordinator for a rectangular tile mesh.

    ``advance`` evaluates all swap conditions from one published-epoch
    snapshot, then promotes every eligible tile together.
    """

    def __init__(self, tiles_x: int, tiles_y: int, initial_state: State,
                 *, epoch_bits: int = 32) -> None:
        if tiles_x < 1 or tiles_y < 1:
            raise ValueError("mesh dimensions must both be positive")
        self.tiles_x = tiles_x
        self.tiles_y = tiles_y
        self.buffers = [
            [EpochBuffer(initial_state, epoch_bits=epoch_bits)
             for _ in range(tiles_x)]
            for _ in range(tiles_y)
        ]

    def tile_at(self, x: int, y: int) -> EpochBuffer[State]:
        if not (0 <= x < self.tiles_x and 0 <= y < self.tiles_y):
            raise ValueError("tile coordinates are outside this mesh")
        return self.buffers[y][x]

    def publish(self, x: int, y: int, next_state: State,
                *, epoch: int | None = None) -> None:
        tile = self.tile_at(x, y)
        tile.publish(next_state, tile.current_epoch + 1 if epoch is None else epoch)

    def advance(self) -> list[tuple[int, int]]:
        """Swap eligible tiles and return their coordinates in row-major order."""
        published = [[self.buffers[y][x].published_epoch
                      for x in range(self.tiles_x)] for y in range(self.tiles_y)]
        eligible: list[tuple[int, int]] = []
        for y in range(self.tiles_y):
            for x in range(self.tiles_x):
                tile = self.buffers[y][x]
                neighbor_epochs = [
                    published[y + dy][x + dx]
                    for dx, dy in _MOORE
                    if 0 <= x + dx < self.tiles_x and 0 <= y + dy < self.tiles_y
                ]
                if tile.ready_to_swap(neighbor_epochs):
                    eligible.append((x, y))
        for x, y in eligible:
            tile = self.buffers[y][x]
            neighbor_epochs = [
                published[y + dy][x + dx]
                for dx, dy in _MOORE
                if 0 <= x + dx < self.tiles_x and 0 <= y + dy < self.tiles_y
            ]
            tile.swap(neighbor_epochs)
        return eligible
