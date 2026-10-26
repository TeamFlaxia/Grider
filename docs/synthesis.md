# Synthesis and timing baseline

Run `python scripts/synth_report.py` with Yosys installed. The report synthesizes a one-cell processing element and a 2×2 tile proxy, and saves raw Yosys JSON and logs under `build/synthesis/`. CI uploads those files as the `grider-synthesis-reports` artifact.

The report records the exact architectural state-bit count, Yosys memory cells before memory mapping, and generic mapped-cell counts. Generic cells are useful for comparing RTL revisions; they are not physical area units. The default 16×16 tile has 256 lanes and 1,081,344 state bits (256 × 32 words × 132 bits). The default 2×2 mesh has 4,325,376 state bits before adding compute logic and interconnect.

The RTL currently resets every register and SRAM element asynchronously and exposes combinational reads. Those choices can prevent inference of block RAM or SRAM macros; the premap Yosys report checks what the tool actually inferred.

Fmax requires a target FPGA part or ASIC standard-cell library, plus timing constraints such as clock period, input/output delays, and PVT corner. The generic synthesis job deliberately does not turn a gate count into a fabricated MHz estimate. Once a target is selected, add technology mapping and static timing analysis for that platform.