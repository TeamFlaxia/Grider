# Synthesis and timing baseline

CI runs Yosys on one processing element through `memory_collect` and records the inferred memory cells and structural state bits. The report and full Yosys log are uploaded as the `grider-synthesis-reports` artifact.

Each PE has 16 132-bit registers and 16 132-bit SRAM words, for 4,224 state bits. The default 16×16 tile therefore contains 1,081,344 state bits. The default 2×2 mesh contains 4,325,376 state bits before compute logic and interconnect.

The full coarse-synthesis pass did not finish within the 5-minute CI limit for a single PE. The CI report therefore stops before memory mapping; its cell counts are not physical area. The RTL's asynchronous reset of every array element and combinational read ports are likely to prevent block RAM or SRAM macro inference; the Yosys report provides the exact inferred memory-cell count.

Fmax and physical area require a target FPGA part or ASIC standard-cell library, plus timing constraints such as clock period, I/O delays, and PVT corner. Once selected, technology mapping and static timing analysis should be added for that platform.