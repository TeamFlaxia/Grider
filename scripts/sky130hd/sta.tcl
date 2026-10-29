# SPDX-License-Identifier: Apache-2.0

set sky130hd_platform /OpenROAD-flow-scripts/flow/platforms/sky130hd
read_lef -tech $sky130hd_platform/lef/sky130_fd_sc_hd.tlef
read_lef -library $sky130hd_platform/lef/sky130_fd_sc_hd_merged.lef
read_liberty $::env(SKY130HD_LIB)
read_verilog build/sky130hd/grider_tile_mapped.v
link_design grider_tile
create_clock -name core_clk -period 100.0 [get_ports clk]
set_clock_transition 0.10 [get_clocks core_clk]
set_clock_uncertainty 0.0 [get_clocks core_clk]
report_checks -path_delay max -from [all_registers] -to [all_registers] -format full_clock_expanded -digits 4
