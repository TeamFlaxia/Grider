# Tile update epochs

`grider.epoch.EpochBuffer` and `rtl/grider_epoch_buffer.sv` define the same
double-buffer handshake for a complete tile state image. The writer stages a
new image tagged with `current_epoch + 1`; publication does not change the
visible state. The image becomes current only after each required in-mesh
Moore neighbor has published that exact epoch.

Neighbor slots use N, NE, E, SE, S, SW, W, NW order. The `required_neighbors`
mask excludes mesh boundaries. An absent neighbor is not a synchronization
participant. Epoch arithmetic wraps at the configured width.

The Python `EpochMesh.advance` method snapshots every published epoch before
deciding which tiles can swap. This prevents row-major iteration order from
allowing one tile to observe another tile's new epoch midway through a mesh
advance.

The RTL module is a reusable tile-state buffer and handshake primitive. The
existing `grider_mesh` remains lockstep; wiring its tile memories to this
primitive is a separate integration step.
