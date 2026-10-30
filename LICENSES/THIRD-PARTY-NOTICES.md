<!-- SPDX-License-Identifier: Apache-2.0 -->

# Third-party notices

These notices identify external inputs and generated files used by the CI
flow. They do not change the license of any upstream work.

## SRAM22

The Sky130 SRAM macro generator is installed from
[`ucb-substrate/sram22`](https://github.com/ucb-substrate/sram22) at commit
`6ec35d5acc777eeaa199730d7976554e3b3fc50c`. Its source is distributed under
the BSD 3-Clause License; the license text is preserved in
[`SRAM22-BSD-3-Clause.txt`](SRAM22-BSD-3-Clause.txt). CI uploads generated
macro views separately from the Git source tree. This notice records the
generator provenance and does not determine the license of generated outputs.

## SkyWater SKY130HD

CI downloads `sky130_fd_sc_hd__tt_025C_1v80.lib` from
[`efabless/skywater-pdk-libs-sky130_fd_sc_hd`](https://github.com/efabless/skywater-pdk-libs-sky130_fd_sc_hd)
at commit `5a42fd01a0eeb2338340438443c7062e198d97a4`. That upstream file is
under Apache-2.0. It is used as a build input and is not included in the
repository or uploaded workflow artifact.

The Yosys, OpenROAD, and other CI tools are installed or run externally; their
source and licenses are not copied into this repository.
