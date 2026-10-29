# Datapath-width exploration

`grider.widths.TileWidthConfig` computes exact logical state capacity for a
selected payload width, including the four-bit type tag on each register and
SRAM word. The sweep compares 32-bit and 64-bit payloads against the current
128-bit baseline and reports how many chunks a 128-bit operation would need.

Run `python scripts/sky130hd/width_sweep.py` to print the table. With the
current 16×16 tile, 16 registers and 16 SRAM words per lane, the logical state
is:

| Payload width | State bits per tile | State KiB per tile | 128-bit chunks |
|---:|---:|---:|---:|
| 32 | 294,912 | 36 | 4 |
| 64 | 557,056 | 68 | 2 |
| 128 | 1,081,344 | 132 | 1 |

These values describe storage capacity only. The RTL still has a fixed
128-bit payload interface and arithmetic datapath, so this sweep does not
claim area or timing results. A `DATA_WIDTH`-parameterized tile, wide-operation
sequencing, SRAM macro variants, and full 16×16 synthesis/STA runs are needed
to complete PPA evaluation for #10.
