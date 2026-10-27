`timescale 1ns/1ps
module tb_grider_tile;
    localparam integer LANES = 256;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0;
    reg instruction_valid = 1'b0;
    wire instruction_ready;
    wire instruction_done;
    reg host_write_enable = 1'b0;
    reg host_read_enable = 1'b0;
    wire host_access_ready;
    wire host_read_valid;
    reg host_memory_select = 1'b0;
    reg [7:0] host_lane = '0;
    reg [3:0] host_index = '0;
    reg [127:0] host_write_data = '0;
    reg [3:0] host_write_type = '0;
    wire [127:0] host_read_data;
    wire [3:0] host_read_type;
    reg [16*132-1:0] halo_north = '0;
    reg [16*132-1:0] halo_south = '0;
    reg [16*132-1:0] halo_east = '0;
    reg [16*132-1:0] halo_west = '0;
    reg [15:0] halo_north_valid = '0;
    reg [15:0] halo_south_valid = '0;
    reg [15:0] halo_east_valid = '0;
    reg [15:0] halo_west_valid = '0;
    reg [131:0] halo_north_east = '0;
    reg [131:0] halo_south_east = '0;
    reg [131:0] halo_south_west = '0;
    reg [131:0] halo_north_west = '0;
    reg halo_north_east_valid = 1'b0;
    reg halo_south_east_valid = 1'b0;
    reg halo_south_west_valid = 1'b0;
    reg halo_north_west_valid = 1'b0;
    wire [16*132-1:0] edge_north;
    wire [16*132-1:0] edge_south;
    wire [16*132-1:0] edge_east;
    wire [16*132-1:0] edge_west;
    wire [131:0] edge_north_east;
    wire [131:0] edge_south_east;
    wire [131:0] edge_south_west;
    wire [131:0] edge_north_west;
    reg [4:0] opcode = '0;
    reg [3:0] dst = '0;
    reg [3:0] src_a = '0;
    reg [3:0] src_b = '0;
    reg [3:0] src_c = '0;
    reg [127:0] immediate = '0;
    reg [3:0] dtype = '0;
    reg [LANES-1:0] lane_mask = '1;

    grider_tile dut (.*);

`ifndef GRIDER_USE_SRAM22
    // Read the inferred arrays directly for the final whole-tile comparison.
    // Host-port timing is tested above; serially reading 8,192 words would
    // add thousands of unnecessary clock cycles to the RTL regression.
    wire [131:0] debug_register_state [0:LANES*16-1];
    wire [131:0] debug_sram_state [0:LANES*16-1];
    genvar debug_lane;
    genvar debug_word;
    generate
        for (debug_lane = 0; debug_lane < LANES; debug_lane = debug_lane + 1) begin : debug_lanes
            for (debug_word = 0; debug_word < 16; debug_word = debug_word + 1) begin : debug_words
                assign debug_register_state[debug_lane*16+debug_word] =
                    dut.lane_memories[debug_lane].register_valid[debug_word]
                        ? dut.lane_memories[debug_lane].register_words[debug_word]
                        : {4'h4, 128'b0};
                assign debug_sram_state[debug_lane*16+debug_word] =
                    dut.lane_memories[debug_lane].local_sram_valid[debug_word]
                        ? dut.lane_memories[debug_lane].local_sram_words[debug_word]
                        : {4'h4, 128'b0};
            end
        end
    endgenerate
`endif

    task automatic host_write(input bit is_sram, input integer lane,
                              input integer index, input logic [127:0] data,
                              input logic [3:0] tag);
        begin
            @(negedge clk);
            host_read_enable = 1'b0;
            host_write_enable = 1'b1;
            host_memory_select = is_sram;
            host_lane = lane[7:0];
            host_index = index[3:0];
            host_write_data = data;
            host_write_type = tag;
            #1;
            if (instruction_ready !== 1'b0 || host_access_ready !== 1'b1)
                $fatal(1, "host write must own an idle state port");
            @(posedge clk); #1;
            if (instruction_done !== 1'b0 || host_read_valid !== 1'b0)
                $fatal(1, "host write must not complete an instruction or host read");
            host_write_enable = 1'b0;
        end
    endtask

    task automatic host_read_word(input bit is_sram, input integer lane,
                                  input integer index, output logic [127:0] data,
                                  output logic [3:0] tag);
        begin
            @(negedge clk);
            host_write_enable = 1'b0;
            host_read_enable = 1'b1;
            host_memory_select = is_sram;
            host_lane = lane[7:0];
            host_index = index[3:0];
            #1;
            if (host_access_ready !== 1'b1 || instruction_ready !== 1'b0)
                $fatal(1, "host read request was not accepted while the tile was idle");
            @(posedge clk); #1;
            if (host_read_valid !== 1'b1)
                $fatal(1, "accepted host read did not return valid data");
            data = host_read_data;
            tag = host_read_type;
            host_read_enable = 1'b0;
        end
    endtask

    task automatic issue(input integer op, input integer d,
                         input integer a, input integer b, input integer c,
                         input logic [127:0] imm, input logic [3:0] tag,
                         input logic [LANES-1:0] mask);
        integer timeout_cycles;
        begin
            @(negedge clk);
            opcode = op[4:0]; dst = d[3:0]; src_a = a[3:0];
            src_b = b[3:0]; src_c = c[3:0]; immediate = imm;
            dtype = tag; lane_mask = mask; instruction_valid = 1'b1;
            #1;
            if (instruction_ready !== 1'b1)
                $fatal(1, "instruction was not ready before the accepting edge");
            @(posedge clk); #1;
            if (instruction_done !== 1'b0 || instruction_ready !== 1'b0 ||
                host_access_ready !== 1'b0)
                $fatal(1, "accepted instruction must enter the busy pipeline");
            instruction_valid = 1'b0;
            timeout_cycles = 0;
            while (instruction_done !== 1'b1) begin
                @(posedge clk); #1;
                timeout_cycles = timeout_cycles + 1;
                if (timeout_cycles > 8)
                    $fatal(1, "instruction pipeline did not retire");
                if ((instruction_done !== 1'b1) &&
                    ((instruction_ready !== 1'b0) || (host_access_ready !== 1'b0)))
                    $fatal(1, "tile ports must remain busy until retirement");
            end
            if (instruction_ready !== 1'b1)
                $fatal(1, "tile must return ready when done is asserted");
        end
    endtask

    integer fd;
    integer rc;
    integer op;
    integer d;
    integer a;
    integer b;
    integer c;
    integer lane;
    integer index;
    reg [7:0] kind;
    reg [127:0] data;
    reg [127:0] imm;
    reg [255:0] mask;
    reg [3:0] tag;
    reg [3:0] tag_hex;
    reg [3:0] op_tag;
    reg [3:0] d4;
    reg [3:0] a4;
    reg [3:0] b4;
    reg [3:0] c4;
    reg [4:0] op5;
    string stim_path;
    integer r;
    integer word_index;
    logic [127:0] read_data;
    logic [3:0] read_type;
    integer timeout_cycles;

    initial begin
        host_memory_select = 1'b0;
        host_read_enable = 1'b0;
        host_lane = '0;
        host_index = '0;
        #1;
        if (instruction_ready !== 1'b0)
            $fatal(1, "instruction_ready must be low during reset");
        repeat (2) @(posedge clk);
        #1;
        if (instruction_done !== 1'b0)
            $fatal(1, "instruction_done must be low during reset");
        @(negedge clk); rst_n = 1'b1;
        #1;
        if (instruction_ready !== 1'b1 || instruction_done !== 1'b0)
            $fatal(1, "reset release must leave the interface ready and idle");
        host_read_word(1'b0, 0, 0, read_data, read_type);
        if (read_data !== 128'b0 || read_type !== 4'h4)
            $fatal(1, "unwritten register must read as zero with the I32 reset tag");
        host_read_word(1'b1, 0, 0, read_data, read_type);
        if (read_data !== 128'b0 || read_type !== 4'h4)
            $fatal(1, "unwritten local SRAM must read as zero with the I32 reset tag");

        if (!$value$plusargs("STIM=%s", stim_path)) $fatal(1, "missing +STIM path");
        fd = $fopen(stim_path, "r");
        if (fd == 0) $fatal(1, "cannot open stimulus file");
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%s", kind);
            if (rc == 1) begin
                if (kind == "R" || kind == "S") begin
                    rc = $fscanf(fd, "%d %d %h %h\n", lane, index, data, tag_hex);
                    if (rc != 4) $fatal(1, "bad register/SRAM stimulus");
                    host_write_enable = 1'b0;
                    host_write(kind == "S", lane, index, data, tag_hex);
                end else if (kind == "I") begin
                    rc = $fscanf(fd, "%d %d %d %d %d %h %h %h\n",
                                 op, d, a, b, c, imm, tag_hex, mask);
                    if (rc != 8) $fatal(1, "bad instruction stimulus");
                    issue(op, d, a, b, c, imm, tag_hex, mask);
                end else begin
                    $fatal(1, "unknown stimulus record %s", kind);
                end
            end
        end
        $fclose(fd);

        // A host write stalls a valid instruction. The same NOP is accepted
        // after the host write releases the state port.
        host_read_word(1'b0, 0, 0, data, tag);
        if (data !== 128'b0 || tag !== 4'h2)
            $fatal(1, "host read after BF16 execution returned the wrong register value");
        @(negedge clk);
        host_write_enable = 1'b1; host_read_enable = 1'b0;
        host_memory_select = 1'b0; host_lane = 0; host_index = 0;
        host_write_data = data; host_write_type = tag;
        opcode = 5'd0; dst = 0; src_a = 0; src_b = 0; src_c = 0;
        immediate = '0; dtype = 4'hf; lane_mask = '1;
        instruction_valid = 1'b1;
        #1;
        if (instruction_ready !== 1'b0 || host_access_ready !== 1'b1)
            $fatal(1, "host write must stall a valid instruction");
        @(posedge clk); #1;
        if (instruction_done !== 1'b0)
            $fatal(1, "stalled instruction must not assert done");
        @(negedge clk);
        host_write_enable = 1'b0;
        #1;
        if (instruction_ready !== 1'b1)
            $fatal(1, "instruction_ready must return after host write");
        @(posedge clk); #1;
        if (instruction_done !== 1'b0 || instruction_ready !== 1'b0)
            $fatal(1, "held instruction must enter the busy pipeline after the stall");
        instruction_valid = 1'b0;
        timeout_cycles = 0;
        while (instruction_done !== 1'b1) begin
            @(posedge clk); #1;
            timeout_cycles = timeout_cycles + 1;
            if (timeout_cycles > 8)
                $fatal(1, "held instruction did not retire");
        end
        @(negedge clk);
        if (instruction_done !== 1'b1)
            $fatal(1, "instruction_done must remain high for one cycle");
        @(posedge clk); #1;
        if (instruction_done !== 1'b0)
            $fatal(1, "instruction_done must clear when no instruction is accepted");

        for (lane = 0; lane < LANES; lane = lane + 1) begin
            for (r = 0; r < 16; r = r + 1) begin
`ifdef GRIDER_USE_SRAM22
                host_read_word(1'b0, lane, r, read_data, read_type);
`else
                read_data = debug_register_state[lane*16+r][127:0];
                read_type = debug_register_state[lane*16+r][131:128];
`endif
                $display("R %0d %0d %032h %01h", lane, r, read_data, read_type);
`ifdef GRIDER_USE_SRAM22
                host_read_word(1'b1, lane, r, read_data, read_type);
`else
                read_data = debug_sram_state[lane*16+r][127:0];
                read_type = debug_sram_state[lane*16+r][131:128];
`endif
                $display("S %0d %0d %032h %01h", lane, r, read_data, read_type);
            end
        end
        $finish;
    end
endmodule

