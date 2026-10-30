# Independent tile issue

`IndependentMeshScheduler` gives each tile its own bounded FIFO and issue PC.
During a model cycle, every tile with a ready non-neighbor instruction may
advance independently. A `NEIGHBOR` instruction carries an epoch and waits
until the tile in its selected direction also has a `NEIGHBOR` at that epoch.
Neighbor reads use a pre-issue mesh snapshot, so simultaneous writes cannot
leak into another tile's read.

`rtl/grider_tile_issue_queue.sv` is the corresponding per-tile ready/valid
queue. It exposes an epoch tag with each instruction so a mesh-level issue
controller can enforce the same neighbor rendezvous. The queue is intended to
be instantiated once per tile and connected to that tile's instruction input.

The existing `grider_mesh` still has one broadcast instruction port. A
per-tile mesh wrapper and cycle comparison against the Python scheduler are
still required before the independent issue path is integrated.
