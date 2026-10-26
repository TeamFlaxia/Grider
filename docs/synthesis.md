# Synthesis and timing baseline

Run `python scripts/synth_report.py` with Yosys installed. CI elaborates one processing element and a 2×2 tile proxy, records Yosys cell counts before memory mapping and after the coarse synthesis pass, and uploads raw JSON and logs under the `grider-synthesis-reports` artifact.

The report records the exact architectural state-bit count, Yosys memory cells before mapping, coarse operator-cell counts, and multiplier/MACC cell counts. These are structural metrics, not physical area. The default 16×16 tile has 256 lanes and 1,081,344 state bits (256 × 32 words × 132 bits). The default 2×2 mesh has 4,325,376 state bits before adding compute logic and interconnect.

A full generic gate mapping of even the 2×2 proxy exceeded the hosted runner's resource window. The coarse report keeps multiplier cells intact, which lets CI inspect the design without pretending those operators have a known physical area.

The RTL asynchronously resets every register and SRAM element and exposes combinational reads. Those choices can prevent block RAM or SRAM macro inference; the premap Yosys report checks what the tool actually inferred.

Fmax and physical area require a target FPGA part or ASIC standard-cell library, plus timing constraints such as clock period, input/output delays, and PVT corner. Once selected, technology mapping and static timing analysis should be added for that platform.