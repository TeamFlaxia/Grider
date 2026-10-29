"""Independent per-tile instruction queues with epoch-safe neighbor issue."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence

from .sim import Instruction, LANES, REGISTERS, Opcode, Tile


@dataclass(frozen=True)
class QueuedInstruction:
    pc: int
    epoch: int
    instruction: Instruction


class TileInstructionQueue:
    """Bounded FIFO and issue PC for a single tile."""

    def __init__(self, depth: int = 4) -> None:
        if depth < 1:
            raise ValueError("queue depth must be positive")
        self.depth = depth
        self.program_counter = 0
        self._queue: deque[QueuedInstruction] = deque()

    @property
    def issue_valid(self) -> bool:
        return bool(self._queue)

    @property
    def head(self) -> QueuedInstruction | None:
        return self._queue[0] if self._queue else None

    def enqueue(self, instruction: Instruction, *, epoch: int = 0) -> bool:
        if len(self._queue) >= self.depth:
            return False
        pc = self.program_counter + len(self._queue)
        self._queue.append(QueuedInstruction(pc, epoch, instruction))
        return True

    def issue(self) -> QueuedInstruction | None:
        if not self._queue:
            return None
        item = self._queue.popleft()
        self.program_counter += 1
        return item


class IndependentMeshScheduler:
    """Issue one queued instruction per ready tile on each model cycle.

    Neighbor instructions carry an epoch. A tile stalls that instruction until
    the tile in its selected mesh direction also has a neighbor instruction at
    the same epoch. All neighbor reads use a mesh-wide pre-issue snapshot.
    """

    _DIRECTIONS = ((0, -1), (1, -1), (1, 0), (1, 1),
                   (0, 1), (-1, 1), (-1, 0), (-1, -1))

    def __init__(self, tiles_x: int = 2, tiles_y: int = 2,
                 *, queue_depth: int = 4) -> None:
        if tiles_x < 1 or tiles_y < 1:
            raise ValueError("mesh dimensions must both be positive")
        self.tiles_x = tiles_x
        self.tiles_y = tiles_y
        self.tiles = [[Tile() for _ in range(tiles_x)] for _ in range(tiles_y)]
        self.queues = [[TileInstructionQueue(queue_depth) for _ in range(tiles_x)]
                       for _ in range(tiles_y)]
        self.cycles = 0
        self.stalled_neighbor_issues = 0

    def tile_at(self, x: int, y: int) -> Tile:
        if not (0 <= x < self.tiles_x and 0 <= y < self.tiles_y):
            raise ValueError("tile coordinates are outside this mesh")
        return self.tiles[y][x]

    def queue_at(self, x: int, y: int) -> TileInstructionQueue:
        if not (0 <= x < self.tiles_x and 0 <= y < self.tiles_y):
            raise ValueError("tile coordinates are outside this mesh")
        return self.queues[y][x]

    def load_program(self, x: int, y: int, program: Iterable[Instruction],
                     *, epoch: int = 0,
                     epochs: Sequence[int] | None = None) -> None:
        queue = self.queue_at(x, y)
        instructions = list(program)
        if epochs is not None and len(epochs) != len(instructions):
            raise ValueError("epochs must contain one value per instruction")
        for index, instruction in enumerate(instructions):
            item_epoch = epoch if epochs is None else epochs[index]
            if not queue.enqueue(instruction, epoch=item_epoch):
                raise BufferError("program exceeds the tile queue; enqueue in smaller batches")

    def cycle(self) -> list[tuple[int, int, int]]:
        """Advance one cycle and return issued (tile_x, tile_y, pc) tuples."""
        snapshot = [[[[tile._rf[lane][register] for register in range(REGISTERS)]
                      for lane in range(LANES)] for tile in row] for row in self.tiles]
        candidates: list[tuple[int, int, QueuedInstruction]] = []
        for y in range(self.tiles_y):
            for x in range(self.tiles_x):
                item = self.queues[y][x].head
                if item is None:
                    continue
                insn = item.instruction
                if int(insn.opcode) == Opcode.NEIGHBOR:
                    dx, dy = self._DIRECTIONS[int(insn.imm) & 0x7]
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.tiles_x and 0 <= ny < self.tiles_y:
                        neighbor = self.queues[ny][nx].head
                        if (neighbor is None or int(neighbor.instruction.opcode) != Opcode.NEIGHBOR
                                or neighbor.epoch != item.epoch):
                            self.stalled_neighbor_issues += 1
                            continue
                candidates.append((x, y, item))

        issued: list[tuple[int, int, int]] = []
        for x, y, item in candidates:
            popped = self.queues[y][x].issue()
            assert popped == item
            insn = item.instruction
            if int(insn.opcode) == Opcode.NEIGHBOR:
                def resolve(lane: int, direction: int, register: int,
                            tile_x: int = x, tile_y: int = y):
                    cell_x, cell_y = lane % 16, lane // 16
                    dx, dy = self._DIRECTIONS[direction & 0x7]
                    gx = tile_x * 16 + cell_x + dx
                    gy = tile_y * 16 + cell_y + dy
                    if not (0 <= gx < self.tiles_x * 16 and 0 <= gy < self.tiles_y * 16):
                        return None
                    tile_x2, cell_x2 = divmod(gx, 16)
                    tile_y2, cell_y2 = divmod(gy, 16)
                    target_lane = cell_y2 * 16 + cell_x2
                    return snapshot[tile_y2][tile_x2][target_lane][register]
                self.tiles[y][x].step(insn, neighbor_resolver=resolve)
            else:
                self.tiles[y][x].step(insn)
            issued.append((x, y, popped.pc))
        self.cycles += 1
        return issued
