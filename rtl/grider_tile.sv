// Grider v0 tile datapath.
// One decoder issues a single instruction to lockstep cells. Each cell owns
// typed registers and local SRAM. BF16 arithmetic, integer/bitwise operations,
// synchronous state updates and same-tile eight-neighbor reads are implemented
// here; the complete v0 behavior is specified in docs/isa.md.
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

    localparam logic [3:0] DT_I4 = 4'h0;
    localparam logic [3:0] DT_I8 = 4'h1;
    localparam logic [3:0] DT_BF16 = 4'h2;
    localparam logic [3:0] DT_I16 = 4'h3;
    localparam logic [3:0] DT_I32 = 4'h4;
    localparam logic [3:0] DT_I64 = 4'h5;
    localparam logic [3:0] DT_U128 = 4'h6;
    localparam logic [3:0] DT_PRED = 4'h7;
    // 4'hf asks the datapath to inherit src_a's type (src_b for SEL).
    localparam logic [3:0] DT_INHERIT = 4'hf;

    function automatic logic dtype_is_valid(input logic [3:0] tag);
        begin
            case (tag)
                DT_I4, DT_I8, DT_BF16, DT_I16, DT_I32, DT_I64, DT_U128, DT_PRED:
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
                OP_ADD, OP_SUB, OP_MUL, OP_MAC, OP_MIN, OP_MAX:
                    opcode_supports_dtype =
                        (tag == DT_I4) || (tag == DT_I8) || (tag == DT_BF16) ||
                        (tag == DT_I16) || (tag == DT_I32) || (tag == DT_I64);
                default: opcode_supports_dtype = 1'b1;
            endcase
        end
    endfunction

    logic [127:0] rf_data [0:LANES-1][0:REG_COUNT-1];
    logic [3:0]   rf_type [0:LANES-1][0:REG_COUNT-1];
    logic [127:0] sram_data [0:LANES-1][0:SRAM_WORDS-1];
    logic [3:0]   sram_type [0:LANES-1][0:SRAM_WORDS-1];

    logic [127:0] lane_result [0:LANES-1];
    logic [3:0]   lane_result_type [0:LANES-1];
    logic         lane_write [0:LANES-1];
    logic         lane_store [0:LANES-1];
    logic [127:0] lane_a [0:LANES-1];
    logic [127:0] lane_b [0:LANES-1];
    logic [127:0] lane_c [0:LANES-1];
    logic [127:0] lane_acc [0:LANES-1];
    logic [3:0]   lane_dtype [0:LANES-1];
    logic signed [127:0] signed_a;
    logic signed [127:0] signed_b;
    logic signed [127:0] signed_min_a;
    logic signed [127:0] signed_min_b;
    integer lane;
    integer x;
    integer y;
    integer nx;
    integer ny;
    integer neighbor;

    // A host write takes the tile's state port for this cycle.
    assign instruction_ready = rst_n && !host_write_enable;

    always_comb begin
        host_read_data = '0;
        host_read_type = DT_I32;
        if (host_lane < LANES) begin
            if (host_memory_select) begin
                if (host_index < SRAM_WORDS) begin
                    host_read_data = sram_data[host_lane][host_index];
                    host_read_type = sram_type[host_lane][host_index];
                end
            end else if (host_index < REG_COUNT) begin
                host_read_data = rf_data[host_lane][host_index];
                host_read_type = rf_type[host_lane][host_index];
            end
        end
    end

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
            edge_north[edge_x*132 +: 132] = {rf_type[edge_x][src_a], rf_data[edge_x][src_a]};
            edge_south[edge_x*132 +: 132] = {rf_type[(TILE_H-1)*TILE_W+edge_x][src_a], rf_data[(TILE_H-1)*TILE_W+edge_x][src_a]};
        end
        for (edge_y = 0; edge_y < TILE_H; edge_y = edge_y + 1) begin
            edge_west[edge_y*132 +: 132] = {rf_type[edge_y*TILE_W][src_a], rf_data[edge_y*TILE_W][src_a]};
            edge_east[edge_y*132 +: 132] = {rf_type[edge_y*TILE_W+TILE_W-1][src_a], rf_data[edge_y*TILE_W+TILE_W-1][src_a]};
        end
        edge_north_west = {rf_type[0][src_a], rf_data[0][src_a]};
        edge_north_east = {rf_type[TILE_W-1][src_a], rf_data[TILE_W-1][src_a]};
        edge_south_west = {rf_type[(TILE_H-1)*TILE_W][src_a], rf_data[(TILE_H-1)*TILE_W][src_a]};
        edge_south_east = {rf_type[LANES-1][src_a], rf_data[LANES-1][src_a]};
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

    always_comb begin
        for (lane = 0; lane < LANES; lane = lane + 1) begin
            lane_result[lane] = '0;
            lane_result_type[lane] = dtype;
            lane_write[lane] = 1'b0;
            lane_store[lane] = 1'b0;
            lane_a[lane] = rf_data[lane][src_a];
            lane_b[lane] = rf_data[lane][src_b];
            lane_c[lane] = rf_data[lane][src_c];
            lane_acc[lane] = rf_data[lane][dst];
            signed_a = '0;
            signed_b = '0;
            signed_min_a = '0;
            signed_min_b = '0;
            if (opcode == OP_SEL) begin
                lane_dtype[lane] = (dtype == DT_INHERIT) ? rf_type[lane][src_b] : dtype;
            end else if (opcode == OP_LOAD) begin
                lane_dtype[lane] = sram_type[lane][immediate[3:0]];
            end else if ((opcode == OP_MOV) || (opcode == OP_NEIGHBOR) || (opcode == OP_STORE)) begin
                lane_dtype[lane] = rf_type[lane][src_a];
            end else if (dtype == DT_INHERIT) begin
                lane_dtype[lane] = rf_type[lane][src_a];
            end else begin
                lane_dtype[lane] = dtype;
            end
            neighbor = -1;
            x = 0;
            y = 0;
            nx = 0;
            ny = 0;

            if (instruction_valid && lane_mask[lane] &&
                ((dtype == DT_INHERIT) || dtype_is_valid(dtype)) &&
                dtype_is_valid(lane_dtype[lane]) &&
                opcode_supports_dtype(opcode, lane_dtype[lane])) begin
                case (opcode)
                    OP_NOP: begin end
                    OP_MOV: begin
                        lane_result[lane] = truncate_by_type(lane_a[lane], rf_type[lane][src_a]);
                        lane_result_type[lane] = rf_type[lane][src_a];
                        lane_write[lane] = 1'b1;
                    end
                    OP_MOVI: begin
                        lane_result[lane] = truncate_by_type(immediate, lane_dtype[lane]);
                        lane_result_type[lane] = lane_dtype[lane];
                        lane_write[lane] = 1'b1;
                    end
                    OP_ADD, OP_SUB, OP_MUL, OP_MAC,
                    OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR,
                    OP_MIN, OP_MAX, OP_SEL: begin
                        signed_a = $signed(sign_extend_by_type(lane_a[lane], lane_dtype[lane]));
                        signed_b = $signed(sign_extend_by_type(lane_b[lane], lane_dtype[lane]));
                        signed_min_a = $signed(sign_extend_by_type(lane_a[lane], lane_dtype[lane]));
                        signed_min_b = $signed(sign_extend_by_type(lane_b[lane], lane_dtype[lane]));
                        if ((lane_dtype[lane] == DT_BF16) &&
                            ((opcode == OP_ADD) || (opcode == OP_SUB) ||
                             (opcode == OP_MUL) || (opcode == OP_MAC) ||
                             (opcode == OP_MIN) || (opcode == OP_MAX))) begin
                            case (opcode)
                                OP_ADD: lane_result[lane] = {112'b0, bf16_add(lane_a[lane][15:0], lane_b[lane][15:0])};
                                OP_SUB: lane_result[lane] = {112'b0, bf16_add(lane_a[lane][15:0], {~lane_b[lane][15], lane_b[lane][14:0]})};
                                OP_MUL: lane_result[lane] = {112'b0, bf16_mul(lane_a[lane][15:0], lane_b[lane][15:0])};
                                OP_MAC: lane_result[lane] = {112'b0, bf16_add(lane_acc[lane][15:0], bf16_mul(lane_a[lane][15:0], lane_b[lane][15:0]))};
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
                            case (opcode)
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
                        lane_result_type[lane] = lane_dtype[lane];
                        lane_write[lane] = 1'b1;
                    end
                    OP_NEIGHBOR: begin
                        x = lane % TILE_W;
                        y = lane / TILE_W;
                        // Direction immediate[2:0]: N, NE, E, SE, S, SW, W, NW.
                        case (immediate[2:0])
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
                            neighbor = ny * TILE_W + nx;
                            lane_result[lane] = rf_data[neighbor][src_a];
                            lane_result_type[lane] = rf_type[neighbor][src_a];
                        end else if ((nx < 0) && (ny < 0)) begin
                            lane_result[lane] = halo_north_west_valid ? halo_north_west[127:0] : '0;
                            lane_result_type[lane] = halo_north_west_valid ? halo_north_west[131:128] : rf_type[lane][src_a];
                        end else if ((nx >= TILE_W) && (ny < 0)) begin
                            lane_result[lane] = halo_north_east_valid ? halo_north_east[127:0] : '0;
                            lane_result_type[lane] = halo_north_east_valid ? halo_north_east[131:128] : rf_type[lane][src_a];
                        end else if ((nx < 0) && (ny >= TILE_H)) begin
                            lane_result[lane] = halo_south_west_valid ? halo_south_west[127:0] : '0;
                            lane_result_type[lane] = halo_south_west_valid ? halo_south_west[131:128] : rf_type[lane][src_a];
                        end else if ((nx >= TILE_W) && (ny >= TILE_H)) begin
                            lane_result[lane] = halo_south_east_valid ? halo_south_east[127:0] : '0;
                            lane_result_type[lane] = halo_south_east_valid ? halo_south_east[131:128] : rf_type[lane][src_a];
                        end else if (nx < 0) begin
                            lane_result[lane] = halo_west_valid[ny] ? halo_west[ny*132 +: 128] : '0;
                            lane_result_type[lane] = halo_west_valid[ny] ? halo_west[ny*132+128 +: 4] : rf_type[lane][src_a];
                        end else if (nx >= TILE_W) begin
                            lane_result[lane] = halo_east_valid[ny] ? halo_east[ny*132 +: 128] : '0;
                            lane_result_type[lane] = halo_east_valid[ny] ? halo_east[ny*132+128 +: 4] : rf_type[lane][src_a];
                        end else if (ny < 0) begin
                            lane_result[lane] = halo_north_valid[nx] ? halo_north[nx*132 +: 128] : '0;
                            lane_result_type[lane] = halo_north_valid[nx] ? halo_north[nx*132+128 +: 4] : rf_type[lane][src_a];
                        end else if (ny >= TILE_H) begin
                            lane_result[lane] = halo_south_valid[nx] ? halo_south[nx*132 +: 128] : '0;
                            lane_result_type[lane] = halo_south_valid[nx] ? halo_south[nx*132+128 +: 4] : rf_type[lane][src_a];
                        end else begin
                            lane_result[lane] = '0;
                            lane_result_type[lane] = lane_dtype[lane];
                        end
                        lane_write[lane] = 1'b1;
                    end
                    OP_LOAD: begin
                        lane_result[lane] = sram_data[lane][immediate[3:0]];
                        lane_result_type[lane] = sram_type[lane][immediate[3:0]];
                        lane_write[lane] = 1'b1;
                    end
                    OP_STORE: begin
                        lane_store[lane] = 1'b1;
                        lane_result[lane] = lane_a[lane];
                        lane_result_type[lane] = rf_type[lane][src_a];
                    end
                    default: begin end
                endcase
            end
        end
    end

    integer i;
    integer r;
    integer w;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            instruction_done <= 1'b0;
            for (i = 0; i < LANES; i = i + 1) begin
                for (r = 0; r < REG_COUNT; r = r + 1) begin
                    rf_data[i][r] <= '0;
                    rf_type[i][r] <= DT_I32;
                end
                for (w = 0; w < SRAM_WORDS; w = w + 1) begin
                    sram_data[i][w] <= '0;
                    sram_type[i][w] <= DT_I32;
                end
            end
        end else begin
            instruction_done <= 1'b0;
            if (host_write_enable) begin
                if ((host_lane < LANES) && dtype_is_valid(host_write_type)) begin
                    if (host_memory_select && (host_index < SRAM_WORDS)) begin
                        sram_data[host_lane][host_index] <= truncate_by_type(host_write_data, host_write_type);
                        sram_type[host_lane][host_index] <= host_write_type;
                    end else if (!host_memory_select && (host_index < REG_COUNT)) begin
                        rf_data[host_lane][host_index] <= truncate_by_type(host_write_data, host_write_type);
                        rf_type[host_lane][host_index] <= host_write_type;
                    end
                end
            end else if (instruction_valid) begin
                instruction_done <= 1'b1;
                for (i = 0; i < LANES; i = i + 1) begin
                    if (lane_mask[i]) begin
                        if (lane_write[i] && (opcode != OP_STORE)) begin
                            rf_data[i][dst] <= lane_result[i];
                            rf_type[i][dst] <= lane_result_type[i];
                        end
                        if (lane_store[i]) begin
                            sram_data[i][immediate[3:0]] <= lane_result[i];
                            sram_type[i][immediate[3:0]] <= lane_result_type[i];
                        end
                    end
                end
            end
        end
    end

endmodule
