# MAC pipeline model

`grider_mac_pipeline.sv` is a three-stage elastic signed MAC datapath. It
separates operand capture, multiply, and accumulate. With an always-ready
consumer, it accepts one operation each cycle (initiation interval 1) and
returns each result after three stages. Ready/valid backpressure holds the
occupied stages without dropping an operation.

`grider.pipeline.MacPipeline` models the same stage movement and reports input
acceptance, output validity, and the result consumed on each model cycle.

This is a datapath primitive, not yet the tile's MAC implementation. The
current tile serializes source reads through one register-file port, so its
overall MAC issue interval is still governed by operand access. Register
banking, accumulator forwarding, and integration into `grider_tile` remain
necessary to close #7.
