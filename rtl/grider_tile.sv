// SPDX-License-Identifier: CERN-OHL-W-2.0

// Grider v0 tile datapath.
// One decoder issues a single in-flight instruction to lockstep cells. Each
// cell uses synchronous single-port memories; operand reads, execution and
// writeback are staged. BF16, integer/bitwise and eight-neighbor operations
// are specified in docs/isa.md.
module grider_tile #(
    parameter integer TILE_W = 16,
    parameter integer TILE_H = 16,
    parameter integer REG_COUNT = 16,
    parameter integer SRAM_WORDS = 16,
    parameter integer LANES = TILE_W * TILE_H
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  instruction_valid,
    output logic                  instruction_ready,
    output logic                  instruction_done,
    input  logic                  host_write_enable,
    input  logic                  host_read_enable,
    output logic                  host_access_ready,
    output logic                  host_read_valid,
    input  logic                  host_memory_select, // 0: registers, 1: local SRAM
    input  logic [7:0]            host_lane,
    input  logic [3:0]            host_index,
    input  logic [127:0]          host_write_data,
    input  logic [3:0]            host_write_type,
    output logic [127:0]          host_read_data,
    output logic [3:0]            host_read_type,
    input  logic [TILE_W*132-1:0] halo_north,
    input  logic [TILE_W*132-1:0] halo_south,
    input  logic [TILE_H*132-1:0] halo_east,
    input  logic [TILE_H*132-1:0] halo_west,
    input  logic [TILE_W-1:0]     halo_north_valid,
    input  logic [TILE_W-1:0]     halo_south_valid,
    input  logic [TILE_H-1:0]     halo_east_valid,
    input  logic [TILE_H-1:0]     halo_west_valid,
    input  logic [131:0]          halo_north_east,
    input  logic [131:0]          halo_south_east,
    input  logic [131:0]          halo_south_west,
    input  logic [131:0]          halo_north_west,
    input  logic                  halo_north_east_valid,
    input  logic                  halo_south_east_valid,
    input  logic                  halo_south_west_valid,
    input  logic                  halo_north_west_valid,
    output logic [TILE_W*132-1:0] edge_north,
    output logic [TILE_W*132-1:0] edge_south,
    output logic [TILE_H*132-1:0] edge_east,
    output logic [TILE_H*132-1:0] edge_west,
    output logic [131:0]          edge_north_east,
    output logic [131:0]          edge_south_east,
    output logic [131:0]          edge_south_west,
    output logic [131:0]          edge_north_west,
    input  logic [4:0]            opcode,
    input  logic [3:0]            dst,
    input  logic [3:0]            src_a,
    input  logic [3:0]            src_b,
    input  logic [3:0]            src_c,
    input  logic [127:0]          immediate,
    input  logic [3:0]            dtype,
    input  logic [LANES-1:0]      lane_mask
);

    localparam logic [4:0] OP_NOP      = 5'd0;
    localparam logic [4:0] OP_MOV      = 5'd1;
    localparam logic [4:0] OP_MOVI     = 5'd2;
    localparam logic [4:0] OP_ADD      = 5'd3;
    localparam logic [4:0] OP_SUB      = 5'd4;
    localparam logic [4:0] OP_MUL      = 5'd5;
    localparam logic [4:0] OP_MAC      = 5'd6;
    localparam logic [4:0] OP_AND      = 5'd7;
    localparam logic [4:0] OP_OR       = 5'd8;
    localparam logic [4:0] OP_XOR      = 5'd9;
    localparam logic [4:0] OP_SHL      = 5'd10;
    localparam logic [4:0] OP_SHR      = 5'd11;
    localparam logic [4:0] OP_MIN      = 5'd12;
    localparam logic [4:0] OP_MAX      = 5'd13;
    localparam logic [4:0] OP_SEL      = 5'd14;
    localparam logic [4:0] OP_NEIGHBOR = 5'd15;
    localparam logic [4:0] OP_LOAD     = 5'd16;
    localparam logic [4:0] OP_STORE    = 5'd17;
    localparam logic [4:0] OP_REDUCE_SUM = 5'd18;
    localparam logic [4:0] OP_REDUCE_MAX = 5'd19;
    localparam logic [4:0] OP_CONVERT = 5'd20;

    localparam logic [3:0] DT_I4 = 4'h0;
    localparam logic [3:0] DT_I8 = 4'h1;
    localparam logic [3:0] DT_BF16 = 4'h2;
    localparam logic [3:0] DT_I16 = 4'h3;
    localparam logic [3:0] DT_I32 = 4'h4;
    localparam logic [3:0] DT_I64 = 4'h5;
    localparam logic [3:0] DT_U128 = 4'h6;
    localparam logic [3:0] DT_PRED = 4'h7;
    localparam logic [3:0] DT_F32 = 4'h8;
    // 4'hf asks the datapath to inherit src_a's type (src_b for SEL).
    localparam logic [3:0] DT_INHERIT = 4'hf;

    function automatic logic dtype_is_valid(input logic [3:0] tag);
        begin
            case (tag)
                DT_I4, DT_I8, DT_BF16, DT_I16, DT_I32, DT_I64, DT_U128, DT_PRED, DT_F32:
                    dtype_is_valid = 1'b1;
                default: dtype_is_valid = 1'b0;
            endcase
        end
    endfunction

    function automatic logic opcode_supports_dtype(
        input logic [4:0] operation,
        input logic [3:0] tag
    );
        begin
            case (operation)
                OP_ADD, OP_SUB, OP_MUL, OP_MAC, OP_MIN, OP_MAX,
                OP_REDUCE_SUM, OP_REDUCE_MAX:
                    opcode_supports_dtype =
                        (tag == DT_I4) || (tag == DT_I8) || (tag == DT_BF16) ||
                        (tag == DT_I16) || (tag == DT_I32) || (tag == DT_I64);
                default: opcode_supports_dtype = 1'b1;
            endcase
        end
    endfunction

    function automatic logic operation_has_src_a(
        input logic [4:0] operation,
        input logic [3:0] type_tag
    );
        begin
            case (operation)
                OP_MOV, OP_ADD, OP_SUB, OP_MUL, OP_MAC, OP_CONVERT,
                OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
                OP_MIN, OP_MAX, OP_SEL, OP_NEIGHBOR, OP_STORE,
                OP_REDUCE_SUM, OP_REDUCE_MAX:
                    operation_has_src_a = 1'b1;
                OP_MOVI: operation_has_src_a = (type_tag == DT_INHERIT);
                default: operation_has_src_a = 1'b0;
            endcase
        end
    endfunction

    function automatic logic operation_has_src_b(input logic [4:0] operation);
        begin
            case (operation)
                OP_ADD, OP_SUB, OP_MUL, OP_MAC,
                OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
                OP_MIN, OP_MAX, OP_SEL:
                    operation_has_src_b = 1'b1;
                default: operation_has_src_b = 1'b0;
            endcase
        end
    endfunction

    function automatic logic operation_has_third_read(input logic [4:0] operation);
        begin
            operation_has_third_read = (operation == OP_MAC) || (operation == OP_SEL);
        end
    endfunction

    function automatic integer same_tile_neighbor(
        input integer source_lane,
        input logic [2:0] direction
    );
        integer source_x;
        integer source_y;
        integer target_x;
        integer target_y;
        begin
            source_x = source_lane % TILE_W;
            source_y = source_lane / TILE_W;
            case (direction)
                3'd0: begin target_x = source_x;     target_y = source_y - 1; end
                3'd1: begin target_x = source_x + 1; target_y = source_y - 1; end
                3'd2: begin target_x = source_x + 1; target_y = source_y;     end
                3'd3: begin target_x = source_x + 1; target_y = source_y + 1; end
                3'd4: begin target_x = source_x;     target_y = source_y + 1; end
                3'd5: begin target_x = source_x - 1; target_y = source_y + 1; end
                3'd6: begin target_x = source_x - 1; target_y = source_y;     end
                default: begin target_x = source_x - 1; target_y = source_y - 1; end
            endcase
            if ((target_x >= 0) && (target_x < TILE_W) &&
                (target_y >= 0) && (target_y < TILE_H))
                same_tile_neighbor = target_y * TILE_W + target_x;
            else
                same_tile_neighbor = -1;
        end
    endfunction

    localparam integer REDUCE_STAGES = (TILE_W > 1) ? $clog2(TILE_W) : 1;

    localparam logic [2:0] ST_IDLE      = 3'd0;
    localparam logic [2:0] ST_WAIT_A    = 3'd1;
    localparam logic [2:0] ST_WAIT_B    = 3'd2;
    localparam logic [2:0] ST_WAIT_C    = 3'd3;
    localparam logic [2:0] ST_WAIT_LOAD = 3'd4;
    localparam logic [2:0] ST_EXEC      = 3'd5;
    localparam logic [2:0] ST_WB        = 3'd6;

    logic [2:0] state;
    logic [4:0] instruction_opcode_q;
    logic [3:0] instruction_dst_q;
    logic [3:0] instruction_src_b_q;
    logic [3:0] instruction_src_c_q;
    logic [127:0] instruction_immediate_q;
    logic [3:0] instruction_dtype_q;
    logic [LANES-1:0] instruction_lane_mask_q;

    logic [131:0] operand_a [0:LANES-1];
    logic [131:0] operand_b [0:LANES-1];
    logic [131:0] operand_c [0:LANES-1];
    logic [131:0] operand_acc [0:LANES-1];
    logic [131:0] operand_neighbor [0:LANES-1];
    logic [131:0] load_operand [0:LANES-1];
    logic [127:0] writeback_data_q [0:LANES-1];
    logic [3:0] writeback_type_q [0:LANES-1];
    logic writeback_write_q [0:LANES-1];
    logic writeback_store_q [0:LANES-1];

    logic rf_port_enable [0:LANES-1];
    logic rf_port_write [0:LANES-1];
    logic [3:0] rf_port_address [0:LANES-1];
    logic [131:0] rf_port_write_data [0:LANES-1];
    logic [131:0] rf_port_read_data [0:LANES-1];
    logic sram_port_enable [0:LANES-1];
    logic sram_port_write [0:LANES-1];
    logic [3:0] sram_port_address [0:LANES-1];
    logic [131:0] sram_port_write_data [0:LANES-1];
    logic [131:0] sram_port_read_data [0:LANES-1];

    logic [7:0] host_read_lane_q;
    logic host_read_memory_select_q;
    logic host_read_address_valid_q;
    logic host_read_accept;

    logic [127:0] lane_result [0:LANES-1];
    logic [3:0]   lane_result_type [0:LANES-1];
    logic         lane_write [0:LANES-1];
    logic         lane_store [0:LANES-1];
    logic [127:0] lane_a [0:LANES-1];
    logic [127:0] lane_b [0:LANES-1];
    logic [127:0] lane_c [0:LANES-1];
    logic [127:0] lane_acc [0:LANES-1];
    logic [3:0]   lane_dtype [0:LANES-1];
    logic [127:0] row_reduction [0:TILE_H-1];
    logic [3:0]   row_reduction_type [0:TILE_H-1];
    logic signed [127:0] signed_a;
    logic signed [127:0] signed_b;
    logic signed [127:0] signed_min_a;
    logic signed [127:0] signed_min_b;
    integer lane;
    integer x;
    integer y;
    integer nx;
    integer ny;
    integer port_lane;
    integer i;
    integer reduce_y;
    integer reduce_x;
    integer reduce_stage;
    integer reduce_stride;
    integer reduce_col;
    logic found_active_lane;
    logic [127:0] reduce_partial [0:TILE_W-1];
    logic [TILE_W-1:0] reduce_valid;
    logic [3:0] reduce_type_work;
    logic reduce_has_nan;
    logic [127:0] reduce_sum_value;
    logic signed [127:0] reduce_left_value;
    logic signed [127:0] reduce_right_value;


    // A host transaction uses a memory port only while the instruction engine is idle.
    assign host_access_ready = rst_n && (state == ST_IDLE);
    // Acceptance is separate from completion: ready returns only after writeback.
    assign instruction_ready = rst_n && (state == ST_IDLE) &&
                               !host_write_enable && !host_read_enable;
    // The host response is valid for the cycle after this request is accepted.
    assign host_read_accept = host_read_enable && !host_write_enable && host_access_ready;

    always_comb begin
        host_read_data = '0;
        host_read_type = DT_I32;
        if (host_read_address_valid_q && (host_read_lane_q < LANES)) begin
            if (host_read_memory_select_q) begin
                host_read_data = sram_port_read_data[host_read_lane_q][127:0];
                host_read_type = sram_port_read_data[host_read_lane_q][131:128];
            end else begin
                host_read_data = rf_port_read_data[host_read_lane_q][127:0];
                host_read_type = rf_port_read_data[host_read_lane_q][131:128];
            end
        end
    end

    genvar memory_lane;
    generate
        for (memory_lane = 0; memory_lane < LANES; memory_lane = memory_lane + 1) begin : lane_memories
            logic [REG_COUNT-1:0] register_valid;
            logic [131:0] register_read_q;
            logic register_read_valid_q;
            logic [SRAM_WORDS-1:0] local_sram_valid;
            logic [131:0] local_sram_read_q;
            logic local_sram_read_valid_q;

`ifdef GRIDER_USE_SRAM22
            logic [127:0] register_payload_q;
            logic [7:0] register_tag_q;
            logic [127:0] local_sram_payload_q;
            logic [7:0] local_sram_tag_q;

            // SRAM22 reset inhibits access; the validity bitmap supplies the
            // architectural zero value without clearing macro contents.
            sram22_64x128m4w8 register_payload_macro (
                .clk(clk), .rstb(rst_n),
                .ce(rf_port_enable[memory_lane]), .we(rf_port_write[memory_lane]),
                .wmask(16'hffff), .addr({2'b00, rf_port_address[memory_lane]}),
                .din(rf_port_write_data[memory_lane][127:0]),
                .dout(register_payload_q)
            );
            sram22_64x8m4w8 register_tag_macro (
                .clk(clk), .rstb(rst_n),
                .ce(rf_port_enable[memory_lane]), .we(rf_port_write[memory_lane]),
                .wmask(1'b1), .addr({2'b00, rf_port_address[memory_lane]}),
                .din({4'b0, rf_port_write_data[memory_lane][131:128]}),
                .dout(register_tag_q)
            );
            sram22_64x128m4w8 local_sram_payload_macro (
                .clk(clk), .rstb(rst_n),
                .ce(sram_port_enable[memory_lane]), .we(sram_port_write[memory_lane]),
                .wmask(16'hffff), .addr({2'b00, sram_port_address[memory_lane]}),
                .din(sram_port_write_data[memory_lane][127:0]),
                .dout(local_sram_payload_q)
            );
            sram22_64x8m4w8 local_sram_tag_macro (
                .clk(clk), .rstb(rst_n),
                .ce(sram_port_enable[memory_lane]), .we(sram_port_write[memory_lane]),
                .wmask(1'b1), .addr({2'b00, sram_port_address[memory_lane]}),
                .din({4'b0, sram_port_write_data[memory_lane][131:128]}),
                .dout(local_sram_tag_q)
            );
            assign register_read_q = {register_tag_q[3:0], register_payload_q};
            assign local_sram_read_q = {local_sram_tag_q[3:0], local_sram_payload_q};
`else
            logic [131:0] register_words [0:REG_COUNT-1];
            logic [131:0] local_sram_words [0:SRAM_WORDS-1];

            // Synchronous one-port read/write. The valid bitmap resets instead
            // of clearing every payload word, preserving SRAM inference.
            always_ff @(posedge clk) begin
                if (rf_port_enable[memory_lane]) begin
                    if (rf_port_write[memory_lane]) begin
                        if (rf_port_address[memory_lane] < REG_COUNT)
                            register_words[rf_port_address[memory_lane]] <=
                                rf_port_write_data[memory_lane];
                    end else if (rf_port_address[memory_lane] < REG_COUNT) begin
                        register_read_q <= register_words[rf_port_address[memory_lane]];
                    end
                end
                if (sram_port_enable[memory_lane]) begin
                    if (sram_port_write[memory_lane]) begin
                        if (sram_port_address[memory_lane] < SRAM_WORDS)
                            local_sram_words[sram_port_address[memory_lane]] <=
                                sram_port_write_data[memory_lane];
                    end else if (sram_port_address[memory_lane] < SRAM_WORDS) begin
                        local_sram_read_q <= local_sram_words[sram_port_address[memory_lane]];
                    end
                end
            end
`endif

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    register_valid <= '0;
                    register_read_valid_q <= 1'b0;
                    local_sram_valid <= '0;
                    local_sram_read_valid_q <= 1'b0;
                end else begin
                    if (rf_port_enable[memory_lane]) begin
                        if (rf_port_write[memory_lane]) begin
                            if (rf_port_address[memory_lane] < REG_COUNT)
                                register_valid[rf_port_address[memory_lane]] <= 1'b1;
                        end else if (rf_port_address[memory_lane] < REG_COUNT) begin
                            register_read_valid_q <= register_valid[rf_port_address[memory_lane]];
                        end else begin
                            register_read_valid_q <= 1'b0;
                        end
                    end
                    if (sram_port_enable[memory_lane]) begin
                        if (sram_port_write[memory_lane]) begin
                            if (sram_port_address[memory_lane] < SRAM_WORDS)
                                local_sram_valid[sram_port_address[memory_lane]] <= 1'b1;
                        end else if (sram_port_address[memory_lane] < SRAM_WORDS) begin
                            local_sram_read_valid_q <= local_sram_valid[sram_port_address[memory_lane]];
                        end else begin
                            local_sram_read_valid_q <= 1'b0;
                        end
                    end
                end
            end

            assign rf_port_read_data[memory_lane] = register_read_valid_q
                ? register_read_q : {DT_I32, 128'b0};
            assign sram_port_read_data[memory_lane] = local_sram_read_valid_q
                ? local_sram_read_q : {DT_I32, 128'b0};
        end
    endgenerate

    integer edge_x;
    integer edge_y;
    always_comb begin
        edge_north = '0;
        edge_south = '0;
        edge_east = '0;
        edge_west = '0;
        edge_north_east = '0;
        edge_south_east = '0;
        edge_south_west = '0;
        edge_north_west = '0;
        for (edge_x = 0; edge_x < TILE_W; edge_x = edge_x + 1) begin
            edge_north[edge_x*132 +: 132] = operand_a[edge_x];
            edge_south[edge_x*132 +: 132] = operand_a[(TILE_H-1)*TILE_W+edge_x];
        end
        for (edge_y = 0; edge_y < TILE_H; edge_y = edge_y + 1) begin
            edge_west[edge_y*132 +: 132] = operand_a[edge_y*TILE_W];
            edge_east[edge_y*132 +: 132] = operand_a[edge_y*TILE_W+TILE_W-1];
        end
        edge_north_west = operand_a[0];
        edge_north_east = operand_a[TILE_W-1];
        edge_south_west = operand_a[(TILE_H-1)*TILE_W];
        edge_south_east = operand_a[LANES-1];
    end

    function automatic logic [127:0] sign_extend_by_type(
        input logic [127:0] value,
        input logic [3:0] tag
    );
        logic [127:0] extended;
        begin
            extended = value;
            case (tag)
                DT_I4:  extended = {{124{value[3]}}, value[3:0]};
                DT_I8:  extended = {{120{value[7]}}, value[7:0]};
                DT_I16: extended = {{112{value[15]}}, value[15:0]};
                DT_I32: extended = {{96{value[31]}}, value[31:0]};
                DT_I64: extended = {{64{value[63]}}, value[63:0]};
                default: extended = value;
            endcase
            sign_extend_by_type = extended;
        end
    endfunction

    function automatic logic [127:0] truncate_by_type(
        input logic [127:0] value,
        input logic [3:0] tag
    );
        begin
            case (tag)
                DT_I4:  truncate_by_type = {{124{1'b0}}, value[3:0]};
                DT_I8:  truncate_by_type = {{120{1'b0}}, value[7:0]};
                DT_BF16: truncate_by_type = {{112{1'b0}}, value[15:0]};
                DT_I16: truncate_by_type = {{112{1'b0}}, value[15:0]};
                DT_I32: truncate_by_type = {{96{1'b0}}, value[31:0]};
                DT_F32: truncate_by_type = {{96{1'b0}}, value[31:0]};
                DT_I64: truncate_by_type = {{64{1'b0}}, value[63:0]};
                DT_PRED: truncate_by_type = {{127{1'b0}}, value[0]};
                default: truncate_by_type = value;
            endcase
        end
    endfunction

    function automatic logic [11:0] bf16_shift_right_sticky(
        input logic [11:0] value,
        input integer amount
    );
        logic [11:0] shifted;
        logic discarded;
        integer bit_index;
        begin
            discarded = 1'b0;
            if (amount >= 12) begin
                shifted = '0;
                shifted[0] = |value;
            end else if (amount <= 0) begin
                shifted = value;
            end else begin
                shifted = value >> amount;
                for (bit_index = 0; bit_index < 12; bit_index = bit_index + 1) begin
                    if (bit_index < amount)
                        discarded = discarded | value[bit_index];
                end
                shifted[0] = shifted[0] | discarded;
            end
            bf16_shift_right_sticky = shifted;
        end
    endfunction

    // Pack a normalized 12-bit significand (8 significant bits + 4 guard bits)
    // into BF16 using round-to-nearest, ties-to-even.
    function automatic logic [15:0] bf16_round_pack(
        input logic sign_bit,
        input integer exponent_in,
        input logic [11:0] extended_significand
    );
        integer exponent;
        logic [11:0] ext;
        logic [8:0] rounded;
        logic round_up;
        logic already_subnormal;
        begin
            exponent = exponent_in;
            ext = extended_significand;
            already_subnormal = (exponent == 1) && !ext[11];
            if (already_subnormal) begin
                exponent = 0;
            end else if (exponent <= 0) begin
                ext = bf16_shift_right_sticky(ext, 1 - exponent);
                exponent = 0;
            end
            round_up = ext[3] && (ext[2] || ext[1] || ext[0] || ext[4]);
            rounded = {1'b0, ext[11:4]} + round_up;
            if (rounded[8]) begin
                rounded = rounded >> 1;
                exponent = exponent + 1;
            end
            if (exponent >= 255) begin
                bf16_round_pack = {sign_bit, 8'hff, 7'h00};
            end else if ((exponent == 0) && rounded[7]) begin
                bf16_round_pack = {sign_bit, 8'h01, rounded[6:0]};
            end else if ((exponent == 0) || (rounded[7:0] == 0)) begin
                bf16_round_pack = {sign_bit, 8'h00, rounded[6:0]};
            end else begin
                bf16_round_pack = {sign_bit, exponent[7:0], rounded[6:0]};
            end
        end
    endfunction

    function automatic logic [15:0] bf16_add(
        input logic [15:0] a_value,
        input logic [15:0] b_value
    );
        integer exp_a;
        integer exp_b;
        integer exponent;
        integer difference;
        integer shift_index;
        logic sign_a;
        logic sign_b;
        logic sign_result;
        logic [7:0] sig_a;
        logic [7:0] sig_b;
        logic [11:0] ext_a;
        logic [11:0] ext_b;
        logic [11:0] large_ext;
        logic [11:0] small_ext;
        logic [11:0] aligned_small;
        logic [11:0] work_ext;
        logic [12:0] sum_ext;
        logic [15:0] a_abs;
        logic [15:0] b_abs;
        begin
            sign_a = a_value[15]; sign_b = b_value[15];
            exp_a = (a_value[14:7] == 0) ? 1 : a_value[14:7];
            exp_b = (b_value[14:7] == 0) ? 1 : b_value[14:7];
            sig_a = (a_value[14:7] == 0) ? {1'b0, a_value[6:0]} : {1'b1, a_value[6:0]};
            sig_b = (b_value[14:7] == 0) ? {1'b0, b_value[6:0]} : {1'b1, b_value[6:0]};
            ext_a = {sig_a, 4'b0}; ext_b = {sig_b, 4'b0};
            a_abs = {1'b0, a_value[14:0]}; b_abs = {1'b0, b_value[14:0]};
            sign_result = 1'b0; exponent = 0; work_ext = '0;
            if ((a_value[14:7] == 8'hff && a_value[6:0] != 0) ||
                (b_value[14:7] == 8'hff && b_value[6:0] != 0)) begin
                bf16_add = 16'h7fc0;
            end else if ((a_value[14:7] == 8'hff) && (b_value[14:7] == 8'hff) && (sign_a != sign_b)) begin
                bf16_add = 16'h7fc0;
            end else if (a_value[14:7] == 8'hff) begin
                bf16_add = a_value;
            end else if (b_value[14:7] == 8'hff) begin
                bf16_add = b_value;
            end else if ((a_abs == 0) && (b_abs == 0)) begin
                bf16_add = {sign_a & sign_b, 15'h0000};
            end else begin
                if ((exp_a > exp_b) || ((exp_a == exp_b) && (sig_a >= sig_b))) begin
                    large_ext = ext_a; small_ext = ext_b; exponent = exp_a; sign_result = sign_a;
                    difference = exp_a - exp_b;
                end else begin
                    large_ext = ext_b; small_ext = ext_a; exponent = exp_b; sign_result = sign_b;
                    difference = exp_b - exp_a;
                end
                aligned_small = bf16_shift_right_sticky(small_ext, difference);
                if (sign_a == sign_b) begin
                    sum_ext = {1'b0, large_ext} + {1'b0, aligned_small};
                    if (sum_ext[12]) begin
                        work_ext = sum_ext[12:1];
                        work_ext[0] = work_ext[0] | sum_ext[0];
                        exponent = exponent + 1;
                    end else begin
                        work_ext = sum_ext[11:0];
                    end
                end else begin
                    work_ext = large_ext - aligned_small;
                    if (work_ext == 0) begin
                        sign_result = 1'b0;
                        exponent = 0;
                    end else begin
                        for (shift_index = 0; shift_index < 11; shift_index = shift_index + 1) begin
                            if (!work_ext[11] && (exponent > 1)) begin
                                work_ext = work_ext << 1;
                                exponent = exponent - 1;
                            end
                        end
                    end
                end
                bf16_add = bf16_round_pack(sign_result, exponent, work_ext);
            end
        end
    endfunction

    function automatic logic [15:0] bf16_mul(
        input logic [15:0] a_value,
        input logic [15:0] b_value
    );
        integer exp_a;
        integer exp_b;
        integer exponent;
        integer normalize_step;
        logic sign_result;
        logic [7:0] sig_a;
        logic [7:0] sig_b;
        logic [15:0] product;
        logic [11:0] ext;
        begin
            sign_result = a_value[15] ^ b_value[15];
            exp_a = (a_value[14:7] == 0) ? 1 : a_value[14:7];
            exp_b = (b_value[14:7] == 0) ? 1 : b_value[14:7];
            sig_a = (a_value[14:7] == 0) ? {1'b0, a_value[6:0]} : {1'b1, a_value[6:0]};
            sig_b = (b_value[14:7] == 0) ? {1'b0, b_value[6:0]} : {1'b1, b_value[6:0]};
            for (normalize_step = 0; normalize_step < 7; normalize_step = normalize_step + 1) begin
                if ((sig_a != 0) && !sig_a[7]) begin sig_a = sig_a << 1; exp_a = exp_a - 1; end
                if ((sig_b != 0) && !sig_b[7]) begin sig_b = sig_b << 1; exp_b = exp_b - 1; end
            end
            product = sig_a * sig_b;
            if ((a_value[14:7] == 8'hff && a_value[6:0] != 0) ||
                (b_value[14:7] == 8'hff && b_value[6:0] != 0)) begin
                bf16_mul = 16'h7fc0;
            end else if (((a_value[14:7] == 8'hff) && ((b_value & 16'h7fff) == 0)) ||
                         ((b_value[14:7] == 8'hff) && ((a_value & 16'h7fff) == 0))) begin
                bf16_mul = 16'h7fc0;
            end else if ((a_value[14:7] == 8'hff) || (b_value[14:7] == 8'hff)) begin
                bf16_mul = {sign_result, 8'hff, 7'h00};
            end else if ((sig_a == 0) || (sig_b == 0)) begin
                bf16_mul = {sign_result, 15'h0000};
            end else begin
                exponent = exp_a + exp_b - 127;
                if (product[15]) begin
                    exponent = exponent + 1;
                    ext = product[15:4];
                    ext[0] = ext[0] | (|product[3:0]);
                end else begin
                    ext = product[14:3];
                    ext[0] = ext[0] | (|product[2:0]);
                end
                bf16_mul = bf16_round_pack(sign_result, exponent, ext);
            end
        end
    endfunction

    function automatic logic bf16_less_than(
        input logic [15:0] a_value,
        input logic [15:0] b_value
    );
        logic a_zero;
        logic b_zero;
        begin
            a_zero = (a_value[14:0] == 0);
            b_zero = (b_value[14:0] == 0);
            if (a_zero && b_zero) bf16_less_than = 1'b0;
            else if (a_value[15] != b_value[15]) bf16_less_than = a_value[15];
            else if (a_value[15]) bf16_less_than = (a_value[14:0] > b_value[14:0]);
            else bf16_less_than = (a_value[14:0] < b_value[14:0]);
        end
    endfunction

    function automatic logic [31:0] bf16_to_f32(input logic [15:0] value);
        begin
            bf16_to_f32 = {value, 16'b0};
        end
    endfunction

    function automatic logic [15:0] f32_to_bf16(input logic [31:0] value);
        logic [15:0] upper;
        logic [15:0] rounded;
        begin
            upper = value[31:16];
            if ((value[30:23] == 8'hff) && (value[22:0] != 0)) begin
                f32_to_bf16 = 16'h7fc0;
            end else begin
                rounded = upper;
                if ((value[15:0] > 16'h8000) ||
                    ((value[15:0] == 16'h8000) && upper[0]))
                    rounded = upper + 1'b1;
                f32_to_bf16 = rounded;
            end
        end
    endfunction

    function automatic logic [26:0] f32_shift_right_sticky(
        input logic [26:0] value,
        input integer amount
    );
        logic [26:0] shifted;
        logic sticky;
        integer shift_i;
        begin
            if (amount <= 0) begin
                shifted = value;
            end else if (amount >= 27) begin
                shifted = {26'b0, |value};
            end else begin
                shifted = value >> amount;
                sticky = 1'b0;
                for (shift_i = 0; shift_i < 27; shift_i = shift_i + 1)
                    if (shift_i < amount) sticky = sticky | value[shift_i];
                shifted[0] = shifted[0] | sticky;
            end
            f32_shift_right_sticky = shifted;
        end
    endfunction

    function automatic logic [31:0] f32_round_pack(
        input logic sign_bit,
        input integer exponent_in,
        input logic [26:0] ext_in
    );
        integer exponent;
        logic [26:0] ext;
        logic [24:0] rounded;
        begin
            exponent = exponent_in;
            ext = ext_in;
            if (exponent < 1) begin
                ext = f32_shift_right_sticky(ext, 1 - exponent);
                exponent = 1;
            end
            rounded = {1'b0, ext[26:3]} +
                ((ext[2] && (ext[1] || ext[0] || ext[3])) ? 25'd1 : 25'd0);
            if (rounded[24]) begin
                rounded = rounded >> 1;
                exponent = exponent + 1;
            end
            if (exponent >= 255) begin
                f32_round_pack = {sign_bit, 8'hff, 23'b0};
            end else if ((exponent == 1) && !rounded[23]) begin
                f32_round_pack = {sign_bit, 8'h00, rounded[22:0]};
            end else begin
                f32_round_pack = {sign_bit, exponent[7:0], rounded[22:0]};
            end
        end
    endfunction

    function automatic logic [31:0] f32_add(
        input logic [31:0] a_value,
        input logic [31:0] b_value
    );
        logic sign_a;
        logic sign_b;
        logic sign_result;
        logic [7:0] exp_a_field;
        logic [7:0] exp_b_field;
        integer exp_a;
        integer exp_b;
        integer exponent;
        logic [23:0] sig_a;
        logic [23:0] sig_b;
        logic [26:0] ext_a;
        logic [26:0] ext_b;
        logic [26:0] large_ext;
        logic [26:0] small_ext;
        logic [26:0] aligned_small;
        logic [27:0] work_ext;
        integer norm_i;
        begin
            sign_a = a_value[31];
            sign_b = b_value[31];
            exp_a_field = a_value[30:23];
            exp_b_field = b_value[30:23];
            if (((exp_a_field == 8'hff) && (a_value[22:0] != 0)) ||
                ((exp_b_field == 8'hff) && (b_value[22:0] != 0)) ||
                ((exp_a_field == 8'hff) && (exp_b_field == 8'hff) && (sign_a != sign_b))) begin
                f32_add = 32'h7fc00000;
            end else if (exp_a_field == 8'hff) begin
                f32_add = a_value;
            end else if (exp_b_field == 8'hff) begin
                f32_add = b_value;
            end else if (((a_value[30:0] == 0) && (b_value[30:0] == 0))) begin
                f32_add = {sign_a & sign_b, 31'b0};
            end else begin
                exp_a = (exp_a_field == 0) ? 1 : exp_a_field;
                exp_b = (exp_b_field == 0) ? 1 : exp_b_field;
                sig_a = {(exp_a_field != 0), a_value[22:0]};
                sig_b = {(exp_b_field != 0), b_value[22:0]};
                ext_a = {sig_a, 3'b000};
                ext_b = {sig_b, 3'b000};
                if ((exp_a > exp_b) || ((exp_a == exp_b) && (sig_a >= sig_b))) begin
                    exponent = exp_a;
                    large_ext = ext_a;
                    small_ext = ext_b;
                    sign_result = sign_a;
                    aligned_small = f32_shift_right_sticky(small_ext, exp_a - exp_b);
                end else begin
                    exponent = exp_b;
                    large_ext = ext_b;
                    small_ext = ext_a;
                    sign_result = sign_b;
                    aligned_small = f32_shift_right_sticky(small_ext, exp_b - exp_a);
                end
                if (sign_a == sign_b)
                    work_ext = {1'b0, large_ext} + {1'b0, aligned_small};
                else
                    work_ext = {1'b0, large_ext} - {1'b0, aligned_small};
                if (work_ext == 0) begin
                    f32_add = 32'b0;
                end else begin
                    if (work_ext[27]) begin
                        work_ext = {1'b0, f32_shift_right_sticky(work_ext[26:0], 1)};
                        exponent = exponent + 1;
                    end else begin
                        for (norm_i = 0; norm_i < 27; norm_i = norm_i + 1) begin
                            if (!work_ext[26] && (exponent > 1)) begin
                                work_ext = work_ext << 1;
                                exponent = exponent - 1;
                            end
                        end
                    end
                    f32_add = f32_round_pack(sign_result, exponent, work_ext[26:0]);
                end
            end
        end
    endfunction

    function automatic logic [31:0] f32_mul(
        input logic [31:0] a_value,
        input logic [31:0] b_value
    );
        logic sign_result;
        logic [7:0] exp_a_field;
        logic [7:0] exp_b_field;
        integer exp_a;
        integer exp_b;
        integer exponent;
        integer norm_i;
        logic [23:0] sig_a;
        logic [23:0] sig_b;
        logic [47:0] product;
        logic [26:0] ext;
        begin
            sign_result = a_value[31] ^ b_value[31];
            exp_a_field = a_value[30:23];
            exp_b_field = b_value[30:23];
            sig_a = {(exp_a_field != 0), a_value[22:0]};
            sig_b = {(exp_b_field != 0), b_value[22:0]};
            exp_a = (exp_a_field == 0) ? 1 : exp_a_field;
            exp_b = (exp_b_field == 0) ? 1 : exp_b_field;
            for (norm_i = 0; norm_i < 23; norm_i = norm_i + 1) begin
                if ((sig_a != 0) && !sig_a[23]) begin
                    sig_a = sig_a << 1;
                    exp_a = exp_a - 1;
                end
                if ((sig_b != 0) && !sig_b[23]) begin
                    sig_b = sig_b << 1;
                    exp_b = exp_b - 1;
                end
            end
            product = sig_a * sig_b;
            if (((exp_a_field == 8'hff) && (a_value[22:0] != 0)) ||
                ((exp_b_field == 8'hff) && (b_value[22:0] != 0)) ||
                (((exp_a_field == 8'hff) || (exp_b_field == 8'hff)) &&
                 (((a_value[30:0] == 0)) || (b_value[30:0] == 0)))) begin
                f32_mul = 32'h7fc00000;
            end else if ((exp_a_field == 8'hff) || (exp_b_field == 8'hff)) begin
                f32_mul = {sign_result, 8'hff, 23'b0};
            end else if ((sig_a == 0) || (sig_b == 0)) begin
                f32_mul = {sign_result, 31'b0};
            end else begin
                exponent = exp_a + exp_b - 127;
                if (product[47]) begin
                    exponent = exponent + 1;
                    ext = product[47:21];
                    ext[0] = ext[0] | (|product[20:0]);
                end else begin
                    ext = product[46:20];
                    ext[0] = ext[0] | (|product[19:0]);
                end
                f32_mul = f32_round_pack(sign_result, exponent, ext);
            end
        end
    endfunction

    // Reduction inputs come from the latched source snapshot. Skip the tree
    // unless a reduction is executing; host traffic and ordinary instructions
    // do not need to scan every row.
    always_comb begin
        for (reduce_y = 0; reduce_y < TILE_H; reduce_y = reduce_y + 1) begin
            row_reduction[reduce_y] = '0;
            row_reduction_type[reduce_y] = DT_I32;
        end
        for (reduce_x = 0; reduce_x < TILE_W; reduce_x = reduce_x + 1) begin
            reduce_partial[reduce_x] = '0;
            reduce_valid[reduce_x] = 1'b0;
        end
        found_active_lane = 1'b0;
        reduce_type_work = DT_I32;
        reduce_stage = 0;
        reduce_stride = 1;
        reduce_col = 0;
        reduce_has_nan = 1'b0;
        reduce_sum_value = '0;
        reduce_left_value = '0;
        reduce_right_value = '0;

        if ((state == ST_EXEC) &&
            ((instruction_opcode_q == OP_REDUCE_SUM) ||
             (instruction_opcode_q == OP_REDUCE_MAX))) begin
        for (reduce_y = 0; reduce_y < TILE_H; reduce_y = reduce_y + 1) begin
            row_reduction[reduce_y] = '0;
            row_reduction_type[reduce_y] = DT_I32;
            found_active_lane = 1'b0;
            reduce_type_work = DT_I32;
            reduce_stage = 0;
            reduce_stride = 1;
            reduce_col = 0;
            reduce_has_nan = 1'b0;
            reduce_sum_value = '0;
            reduce_left_value = '0;
            reduce_right_value = '0;

            for (reduce_x = 0; reduce_x < TILE_W; reduce_x = reduce_x + 1) begin
                reduce_partial[reduce_x] = '0;
                reduce_valid[reduce_x] = 1'b0;
                if (!found_active_lane && instruction_lane_mask_q[reduce_y*TILE_W+reduce_x]) begin
                    row_reduction_type[reduce_y] = (instruction_dtype_q == DT_INHERIT) ?
                        operand_a[reduce_y*TILE_W+reduce_x][131:128] : instruction_dtype_q;
                    found_active_lane = 1'b1;
                end
            end

            if (found_active_lane && dtype_is_valid(row_reduction_type[reduce_y]) &&
                opcode_supports_dtype(instruction_opcode_q, row_reduction_type[reduce_y])) begin
                reduce_type_work = row_reduction_type[reduce_y];
                for (reduce_x = 0; reduce_x < TILE_W; reduce_x = reduce_x + 1) begin
                    reduce_partial[reduce_x] = operand_a[reduce_y*TILE_W+reduce_x][127:0];
                    reduce_valid[reduce_x] = instruction_lane_mask_q[reduce_y*TILE_W+reduce_x];
                    if ((reduce_type_work == DT_BF16) && reduce_valid[reduce_x] &&
                        (reduce_partial[reduce_x][14:7] == 8'hff) &&
                        (reduce_partial[reduce_x][6:0] != 0))
                        reduce_has_nan = 1'b1;
                end

                for (reduce_stage = 0; reduce_stage < REDUCE_STAGES; reduce_stage = reduce_stage + 1) begin
                    reduce_stride = 1 << reduce_stage;
                    for (reduce_col = 0; reduce_col < TILE_W; reduce_col = reduce_col + 1) begin
                        if (((reduce_col % (2*reduce_stride)) == 0) &&
                            (reduce_col + reduce_stride < TILE_W)) begin
                            if (reduce_valid[reduce_col] && reduce_valid[reduce_col+reduce_stride]) begin
                                if (instruction_opcode_q == OP_REDUCE_SUM) begin
                                    if (reduce_type_work == DT_BF16) begin
                                        reduce_partial[reduce_col] = {112'b0,
                                            bf16_add(reduce_partial[reduce_col][15:0],
                                                     reduce_partial[reduce_col+reduce_stride][15:0])};
                                    end else begin
                                        reduce_sum_value =
                                            $signed(sign_extend_by_type(reduce_partial[reduce_col], reduce_type_work)) +
                                            $signed(sign_extend_by_type(reduce_partial[reduce_col+reduce_stride], reduce_type_work));
                                        reduce_partial[reduce_col] =
                                            truncate_by_type(reduce_sum_value, reduce_type_work);
                                    end
                                end else if (instruction_opcode_q == OP_REDUCE_MAX) begin
                                    if (reduce_type_work == DT_BF16) begin
                                        if (((reduce_partial[reduce_col][14:7] == 8'hff) &&
                                             (reduce_partial[reduce_col][6:0] != 0)) ||
                                            ((reduce_partial[reduce_col+reduce_stride][14:7] == 8'hff) &&
                                             (reduce_partial[reduce_col+reduce_stride][6:0] != 0))) begin
                                            reduce_partial[reduce_col] = {112'b0, 16'h7fc0};
                                            reduce_has_nan = 1'b1;
                                        end else if (bf16_less_than(
                                            reduce_partial[reduce_col][15:0],
                                            reduce_partial[reduce_col+reduce_stride][15:0])) begin
                                            reduce_partial[reduce_col] = reduce_partial[reduce_col+reduce_stride];
                                        end
                                    end else begin
                                        reduce_left_value =
                                            $signed(sign_extend_by_type(reduce_partial[reduce_col], reduce_type_work));
                                        reduce_right_value =
                                            $signed(sign_extend_by_type(reduce_partial[reduce_col+reduce_stride], reduce_type_work));
                                        if (reduce_right_value > reduce_left_value)
                                            reduce_partial[reduce_col] = reduce_partial[reduce_col+reduce_stride];
                                    end
                                end
                            end else if (!reduce_valid[reduce_col] &&
                                         reduce_valid[reduce_col+reduce_stride]) begin
                                reduce_partial[reduce_col] = reduce_partial[reduce_col+reduce_stride];
                                reduce_valid[reduce_col] = 1'b1;
                            end
                        end
                    end
                end

                if ((instruction_opcode_q == OP_REDUCE_SUM) ||
                    (instruction_opcode_q == OP_REDUCE_MAX)) begin
                    if (reduce_has_nan && (reduce_type_work == DT_BF16))
                        row_reduction[reduce_y] = {112'b0, 16'h7fc0};
                    else if (reduce_valid[0])
                        row_reduction[reduce_y] =
                            truncate_by_type(reduce_partial[0], reduce_type_work);
                end
            end
        end
        end
    end

    always_comb begin
        for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
            rf_port_enable[port_lane] = 1'b0;
            rf_port_write[port_lane] = 1'b0;
            rf_port_address[port_lane] = '0;
            rf_port_write_data[port_lane] = '0;
            sram_port_enable[port_lane] = 1'b0;
            sram_port_write[port_lane] = 1'b0;
            sram_port_address[port_lane] = '0;
            sram_port_write_data[port_lane] = '0;
        end

        if (rst_n) begin
            if (state == ST_IDLE) begin
                if (host_write_enable || host_read_enable) begin
                    for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                        if ((host_lane < LANES) && (host_lane == port_lane)) begin
                            if (host_memory_select) begin
                                if (host_index < SRAM_WORDS) begin
                                    if (host_write_enable && dtype_is_valid(host_write_type)) begin
                                        sram_port_enable[port_lane] = 1'b1;
                                        sram_port_write[port_lane] = 1'b1;
                                        sram_port_address[port_lane] = host_index;
                                        sram_port_write_data[port_lane] =
                                            {host_write_type, truncate_by_type(host_write_data, host_write_type)};
                                    end else if (host_read_enable && !host_write_enable) begin
                                        sram_port_enable[port_lane] = 1'b1;
                                        sram_port_address[port_lane] = host_index;
                                    end
                                end
                            end else if (host_index < REG_COUNT) begin
                                if (host_write_enable && dtype_is_valid(host_write_type)) begin
                                    rf_port_enable[port_lane] = 1'b1;
                                    rf_port_write[port_lane] = 1'b1;
                                    rf_port_address[port_lane] = host_index;
                                    rf_port_write_data[port_lane] =
                                        {host_write_type, truncate_by_type(host_write_data, host_write_type)};
                                end else if (host_read_enable && !host_write_enable) begin
                                    rf_port_enable[port_lane] = 1'b1;
                                    rf_port_address[port_lane] = host_index;
                                end
                            end
                        end
                    end
                end else if (instruction_valid && instruction_ready) begin
                    if (opcode == OP_LOAD) begin
                        for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                            sram_port_enable[port_lane] = 1'b1;
                            sram_port_address[port_lane] = immediate[3:0];
                        end
                    end else if (operation_has_src_a(opcode, dtype)) begin
                        for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                            rf_port_enable[port_lane] = 1'b1;
                            rf_port_address[port_lane] = src_a;
                        end
                    end
                end
            end else if (state == ST_WAIT_A && operation_has_src_b(instruction_opcode_q)) begin
                for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                    rf_port_enable[port_lane] = 1'b1;
                    rf_port_address[port_lane] = instruction_src_b_q;
                end
            end else if (state == ST_WAIT_B && operation_has_third_read(instruction_opcode_q)) begin
                for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                    rf_port_enable[port_lane] = 1'b1;
                    rf_port_address[port_lane] =
                        (instruction_opcode_q == OP_MAC) ? instruction_dst_q : instruction_src_c_q;
                end
            end else if (state == ST_WB) begin
                for (port_lane = 0; port_lane < LANES; port_lane = port_lane + 1) begin
                    if (instruction_lane_mask_q[port_lane]) begin
                        if (writeback_store_q[port_lane]) begin
                            sram_port_enable[port_lane] = 1'b1;
                            sram_port_write[port_lane] = 1'b1;
                            sram_port_address[port_lane] = instruction_immediate_q[3:0];
                            sram_port_write_data[port_lane] =
                                {writeback_type_q[port_lane], writeback_data_q[port_lane]};
                        end else if (writeback_write_q[port_lane]) begin
                            rf_port_enable[port_lane] = 1'b1;
                            rf_port_write[port_lane] = 1'b1;
                            rf_port_address[port_lane] = instruction_dst_q;
                            rf_port_write_data[port_lane] =
                                {writeback_type_q[port_lane], writeback_data_q[port_lane]};
                        end
                    end
                end
            end
        end
    end

    always_comb begin
        for (lane = 0; lane < LANES; lane = lane + 1) begin
            lane_result[lane] = '0;
            lane_result_type[lane] = instruction_dtype_q;
            lane_write[lane] = 1'b0;
            lane_store[lane] = 1'b0;
            lane_a[lane] = operand_a[lane][127:0];
            lane_b[lane] = operand_b[lane][127:0];
            lane_c[lane] = operand_c[lane][127:0];
            lane_acc[lane] = operand_acc[lane][127:0];
            signed_a = '0;
            signed_b = '0;
            signed_min_a = '0;
            signed_min_b = '0;
            if (instruction_opcode_q == OP_SEL) begin
                lane_dtype[lane] = (instruction_dtype_q == DT_INHERIT) ? operand_b[lane][131:128] : instruction_dtype_q;
            end else if ((instruction_opcode_q == OP_REDUCE_SUM) || (instruction_opcode_q == OP_REDUCE_MAX)) begin
                lane_dtype[lane] = row_reduction_type[lane / TILE_W];
            end else if (instruction_opcode_q == OP_LOAD) begin
                lane_dtype[lane] = load_operand[lane][131:128];
            end else if ((instruction_opcode_q == OP_MOV) || (instruction_opcode_q == OP_NEIGHBOR) || (instruction_opcode_q == OP_STORE)) begin
                lane_dtype[lane] = operand_a[lane][131:128];
            end else if (instruction_dtype_q == DT_INHERIT) begin
                lane_dtype[lane] = operand_a[lane][131:128];
            end else begin
                lane_dtype[lane] = instruction_dtype_q;
            end
            x = 0;
            y = 0;
            nx = 0;
            ny = 0;

            if (state == ST_EXEC && instruction_lane_mask_q[lane] &&
                ((instruction_dtype_q == DT_INHERIT) || dtype_is_valid(instruction_dtype_q)) &&
                dtype_is_valid(lane_dtype[lane]) &&
                opcode_supports_dtype(instruction_opcode_q, lane_dtype[lane])) begin
                case (instruction_opcode_q)
                    OP_NOP: begin end
                    OP_MOV: begin
                        lane_result[lane] = truncate_by_type(lane_a[lane], operand_a[lane][131:128]);
                        lane_result_type[lane] = operand_a[lane][131:128];
                        lane_write[lane] = 1'b1;
                    end
                    OP_MOVI: begin
                        lane_result[lane] = truncate_by_type(instruction_immediate_q, lane_dtype[lane]);
                        lane_result_type[lane] = lane_dtype[lane];
                        lane_write[lane] = 1'b1;
                    end
                    OP_CONVERT: begin
                        if ((lane_dtype[lane] == DT_BF16) &&
                            (operand_a[lane][131:128] == DT_F32)) begin
                            lane_result[lane] = {112'b0, f32_to_bf16(lane_a[lane][31:0])};
                            lane_result_type[lane] = DT_BF16;
                            lane_write[lane] = 1'b1;
                        end else if ((lane_dtype[lane] == DT_F32) &&
                                     (operand_a[lane][131:128] == DT_BF16)) begin
                            lane_result[lane] = {96'b0, bf16_to_f32(lane_a[lane][15:0])};
                            lane_result_type[lane] = DT_F32;
                            lane_write[lane] = 1'b1;
                        end
                    end
                    OP_ADD, OP_SUB, OP_MUL, OP_MAC,
                    OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
                    OP_MIN, OP_MAX, OP_SEL: begin
                        signed_a = $signed(sign_extend_by_type(lane_a[lane], lane_dtype[lane]));
                        signed_b = $signed(sign_extend_by_type(lane_b[lane], lane_dtype[lane]));
                        signed_min_a = $signed(sign_extend_by_type(lane_a[lane], lane_dtype[lane]));
                        signed_min_b = $signed(sign_extend_by_type(lane_b[lane], lane_dtype[lane]));
                        if ((lane_dtype[lane] == DT_BF16) &&
                            ((instruction_opcode_q == OP_ADD) || (instruction_opcode_q == OP_SUB) ||
                             (instruction_opcode_q == OP_MUL) || (instruction_opcode_q == OP_MAC) ||
                             (instruction_opcode_q == OP_MIN) || (instruction_opcode_q == OP_MAX))) begin
                            case (instruction_opcode_q)
                                OP_ADD: lane_result[lane] = {112'b0, bf16_add(lane_a[lane][15:0], lane_b[lane][15:0])};
                                OP_SUB: lane_result[lane] = {112'b0, bf16_add(lane_a[lane][15:0], {~lane_b[lane][15], lane_b[lane][14:0]})};
                                OP_MUL: lane_result[lane] = {112'b0, bf16_mul(lane_a[lane][15:0], lane_b[lane][15:0])};
                                OP_MAC: begin
                                    lane_result[lane] = {96'b0,
                                        f32_add(
                                            (operand_acc[lane][131:128] == DT_F32) ?
                                                operand_acc[lane][31:0] :
                                                bf16_to_f32(operand_acc[lane][15:0]),
                                            f32_mul(bf16_to_f32(lane_a[lane][15:0]),
                                                    bf16_to_f32(lane_b[lane][15:0])))};
                                    lane_result_type[lane] = DT_F32;
                                end
                                OP_MIN: begin
                                    if (((lane_a[lane][14:7] == 8'hff) && (lane_a[lane][6:0] != 0)) ||
                                        ((lane_b[lane][14:7] == 8'hff) && (lane_b[lane][6:0] != 0)))
                                        lane_result[lane] = {112'b0, 16'h7fc0};
                                    else
                                        lane_result[lane] = bf16_less_than(lane_b[lane][15:0], lane_a[lane][15:0]) ? {112'b0, lane_b[lane][15:0]} : {112'b0, lane_a[lane][15:0]};
                                end
                                OP_MAX: begin
                                    if (((lane_a[lane][14:7] == 8'hff) && (lane_a[lane][6:0] != 0)) ||
                                        ((lane_b[lane][14:7] == 8'hff) && (lane_b[lane][6:0] != 0)))
                                        lane_result[lane] = {112'b0, 16'h7fc0};
                                    else
                                        lane_result[lane] = bf16_less_than(lane_a[lane][15:0], lane_b[lane][15:0]) ? {112'b0, lane_b[lane][15:0]} : {112'b0, lane_a[lane][15:0]};
                                end
                                default: lane_result[lane] = '0;
                            endcase
                        end else begin
                            case (instruction_opcode_q)
                                OP_ADD: lane_result[lane] = signed_a + signed_b;
                                OP_SUB: lane_result[lane] = signed_a - signed_b;
                                OP_MUL: lane_result[lane] = signed_a * signed_b;
                                OP_MAC: lane_result[lane] = lane_acc[lane] + (signed_a * signed_b);
                                OP_AND: lane_result[lane] = lane_a[lane] & lane_b[lane];
                                OP_OR:  lane_result[lane] = lane_a[lane] | lane_b[lane];
                                OP_XOR: lane_result[lane] = lane_a[lane] ^ lane_b[lane];
                                OP_SHL: lane_result[lane] = lane_a[lane] << lane_b[lane][6:0];
                                OP_SHR: begin
                                    if ((lane_dtype[lane] == DT_U128) ||
                                        (lane_dtype[lane] == DT_BF16) ||
                                        (lane_dtype[lane] == DT_PRED))
                                        lane_result[lane] = lane_a[lane] >> lane_b[lane][6:0];
                                    else
                                        lane_result[lane] = signed_a >>> lane_b[lane][6:0];
                                end
                                OP_MIN: lane_result[lane] = (signed_min_a < signed_min_b) ? signed_min_a : signed_min_b;
                                OP_MAX: lane_result[lane] = (signed_min_a > signed_min_b) ? signed_min_a : signed_min_b;
                                OP_SEL: lane_result[lane] = (lane_a[lane] != 0) ? lane_b[lane] : lane_c[lane];
                                default: lane_result[lane] = '0;
                            endcase
                            lane_result[lane] = truncate_by_type(lane_result[lane], lane_dtype[lane]);
                        end
                        if (!((instruction_opcode_q == OP_MAC) &&
                              (lane_dtype[lane] == DT_BF16)))
                            lane_result_type[lane] = lane_dtype[lane];
                        lane_write[lane] = 1'b1;
                    end
                    OP_NEIGHBOR: begin
                        x = lane % TILE_W;
                        y = lane / TILE_W;
                        // Direction instruction_immediate_q[2:0]: N, NE, E, SE, S, SW, W, NW.
                        case (instruction_immediate_q[2:0])
                            3'd0: begin nx = x;     ny = y - 1; end
                            3'd1: begin nx = x + 1; ny = y - 1; end
                            3'd2: begin nx = x + 1; ny = y;     end
                            3'd3: begin nx = x + 1; ny = y + 1; end
                            3'd4: begin nx = x;     ny = y + 1; end
                            3'd5: begin nx = x - 1; ny = y + 1; end
                            3'd6: begin nx = x - 1; ny = y;     end
                            default: begin nx = x - 1; ny = y - 1; end
                        endcase
                        if ((nx >= 0) && (nx < TILE_W) && (ny >= 0) && (ny < TILE_H)) begin
                            lane_result[lane] = operand_neighbor[lane][127:0];
                            lane_result_type[lane] = operand_neighbor[lane][131:128];
                        end else if ((nx < 0) && (ny < 0)) begin
                            lane_result[lane] = halo_north_west_valid ? halo_north_west[127:0] : '0;
                            lane_result_type[lane] = halo_north_west_valid ? halo_north_west[131:128] : operand_a[lane][131:128];
                        end else if ((nx >= TILE_W) && (ny < 0)) begin
                            lane_result[lane] = halo_north_east_valid ? halo_north_east[127:0] : '0;
                            lane_result_type[lane] = halo_north_east_valid ? halo_north_east[131:128] : operand_a[lane][131:128];
                        end else if ((nx < 0) && (ny >= TILE_H)) begin
                            lane_result[lane] = halo_south_west_valid ? halo_south_west[127:0] : '0;
                            lane_result_type[lane] = halo_south_west_valid ? halo_south_west[131:128] : operand_a[lane][131:128];
                        end else if ((nx >= TILE_W) && (ny >= TILE_H)) begin
                            lane_result[lane] = halo_south_east_valid ? halo_south_east[127:0] : '0;
                            lane_result_type[lane] = halo_south_east_valid ? halo_south_east[131:128] : operand_a[lane][131:128];
                        end else if (nx < 0) begin
                            lane_result[lane] = halo_west_valid[ny] ? halo_west[ny*132 +: 128] : '0;
                            lane_result_type[lane] = halo_west_valid[ny] ? halo_west[ny*132+128 +: 4] : operand_a[lane][131:128];
                        end else if (nx >= TILE_W) begin
                            lane_result[lane] = halo_east_valid[ny] ? halo_east[ny*132 +: 128] : '0;
                            lane_result_type[lane] = halo_east_valid[ny] ? halo_east[ny*132+128 +: 4] : operand_a[lane][131:128];
                        end else if (ny < 0) begin
                            lane_result[lane] = halo_north_valid[nx] ? halo_north[nx*132 +: 128] : '0;
                            lane_result_type[lane] = halo_north_valid[nx] ? halo_north[nx*132+128 +: 4] : operand_a[lane][131:128];
                        end else if (ny >= TILE_H) begin
                            lane_result[lane] = halo_south_valid[nx] ? halo_south[nx*132 +: 128] : '0;
                            lane_result_type[lane] = halo_south_valid[nx] ? halo_south[nx*132+128 +: 4] : operand_a[lane][131:128];
                        end else begin
                            lane_result[lane] = '0;
                            lane_result_type[lane] = lane_dtype[lane];
                        end
                        lane_write[lane] = 1'b1;
                    end
                    OP_LOAD: begin
                        lane_result[lane] = load_operand[lane][127:0];
                        lane_result_type[lane] = load_operand[lane][131:128];
                        lane_write[lane] = 1'b1;
                    end
                    OP_STORE: begin
                        lane_store[lane] = 1'b1;
                        lane_result[lane] = lane_a[lane];
                        lane_result_type[lane] = operand_a[lane][131:128];
                    end
                    OP_REDUCE_SUM, OP_REDUCE_MAX: begin
                        lane_result[lane] = row_reduction[lane / TILE_W];
                        lane_result_type[lane] = row_reduction_type[lane / TILE_W];
                        lane_write[lane] = 1'b1;
                    end
                    default: begin end
                endcase
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            instruction_done <= 1'b0;
            host_read_valid <= 1'b0;
            host_read_lane_q <= '0;
            host_read_memory_select_q <= 1'b0;
            host_read_address_valid_q <= 1'b0;
            instruction_opcode_q <= OP_NOP;
            instruction_dst_q <= '0;
            instruction_src_b_q <= '0;
            instruction_src_c_q <= '0;
            instruction_immediate_q <= '0;
            instruction_dtype_q <= DT_I32;
            instruction_lane_mask_q <= '0;
            for (i = 0; i < LANES; i = i + 1) begin
                operand_a[i] <= {DT_I32, 128'b0};
                operand_b[i] <= {DT_I32, 128'b0};
                operand_c[i] <= {DT_I32, 128'b0};
                operand_acc[i] <= {DT_I32, 128'b0};
                operand_neighbor[i] <= {DT_I32, 128'b0};
                load_operand[i] <= {DT_I32, 128'b0};
                writeback_data_q[i] <= '0;
                writeback_type_q[i] <= DT_I32;
                writeback_write_q[i] <= 1'b0;
                writeback_store_q[i] <= 1'b0;
            end
        end else begin
            instruction_done <= (state == ST_WB);
            host_read_valid <= host_read_accept;
            if (host_read_accept) begin
                host_read_lane_q <= host_lane;
                host_read_memory_select_q <= host_memory_select;
                host_read_address_valid_q <= (host_lane < LANES) &&
                    (host_memory_select ? (host_index < SRAM_WORDS) : (host_index < REG_COUNT));
            end

            case (state)
                ST_IDLE: begin
                    if (instruction_valid && instruction_ready) begin
                        instruction_opcode_q <= opcode;
                        instruction_dst_q <= dst;
                        instruction_src_b_q <= src_b;
                        instruction_src_c_q <= src_c;
                        instruction_immediate_q <= immediate;
                        instruction_dtype_q <= dtype;
                        instruction_lane_mask_q <= lane_mask;
                        if (opcode == OP_LOAD)
                            state <= ST_WAIT_LOAD;
                        else if (operation_has_src_a(opcode, dtype))
                            state <= ST_WAIT_A;
                        else
                            state <= ST_EXEC;
                    end
                end
                ST_WAIT_LOAD: begin
                    for (i = 0; i < LANES; i = i + 1)
                        load_operand[i] <= sram_port_read_data[i];
                    state <= ST_EXEC;
                end
                ST_WAIT_A: begin
                    for (i = 0; i < LANES; i = i + 1) begin
                        operand_a[i] <= rf_port_read_data[i];
                        operand_neighbor[i] <= rf_port_read_data[i];
                        if (instruction_opcode_q == OP_NEIGHBOR) begin
                            if (same_tile_neighbor(i, instruction_immediate_q[2:0]) >= 0)
                                operand_neighbor[i] <=
                                    rf_port_read_data[same_tile_neighbor(i, instruction_immediate_q[2:0])];
                        end
                    end
                    if (operation_has_src_b(instruction_opcode_q))
                        state <= ST_WAIT_B;
                    else
                        state <= ST_EXEC;
                end
                ST_WAIT_B: begin
                    for (i = 0; i < LANES; i = i + 1)
                        operand_b[i] <= rf_port_read_data[i];
                    if (operation_has_third_read(instruction_opcode_q))
                        state <= ST_WAIT_C;
                    else
                        state <= ST_EXEC;
                end
                ST_WAIT_C: begin
                    for (i = 0; i < LANES; i = i + 1) begin
                        if (instruction_opcode_q == OP_MAC)
                            operand_acc[i] <= rf_port_read_data[i];
                        else
                            operand_c[i] <= rf_port_read_data[i];
                    end
                    state <= ST_EXEC;
                end
                ST_EXEC: begin
                    for (i = 0; i < LANES; i = i + 1) begin
                        writeback_data_q[i] <= lane_result[i];
                        writeback_type_q[i] <= lane_result_type[i];
                        writeback_write_q[i] <= lane_write[i];
                        writeback_store_q[i] <= lane_store[i];
                    end
                    state <= ST_WB;
                end
                ST_WB: state <= ST_IDLE;
                default: state <= ST_IDLE;
            endcase
        end
    end
endmodule

