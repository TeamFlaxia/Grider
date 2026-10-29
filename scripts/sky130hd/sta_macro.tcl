# SPDX-License-Identifier: Apache-2.0

set sky130hd_platform /OpenROAD-flow-scripts/flow/platforms/sky130hd
set macro_dir build/sky130hd/sram22
set data_macro_dir $macro_dir/sram22_64x128m4w8
set tag_macro_dir $macro_dir/sram22_64x8m4w8
read_lef -tech $sky130hd_platform/lef/sky130_fd_sc_hd.tlef
read_lef -library $sky130hd_platform/lef/sky130_fd_sc_hd_merged.lef
read_lef $data_macro_dir/sram22_64x128m4w8.lef
read_lef $tag_macro_dir/sram22_64x8m4w8.lef
read_liberty $::env(SKY130HD_LIB)
read_liberty $data_macro_dir/sram22_64x128m4w8_tt_025C_1v80.lib
read_liberty $tag_macro_dir/sram22_64x8m4w8_tt_025C_1v80.lib
read_verilog build/sky130hd/grider_tile_macro_mapped.v
link_design grider_tile
create_clock -name core_clk -period 100.0 [get_ports clk]
set_clock_transition 0.10 [get_clocks core_clk]
set_clock_uncertainty 0.0 [get_clocks core_clk]
report_checks -path_delay max -from [all_registers] -to [all_registers] -format full_clock_expanded -digits 4
