// Grider v0 tile datapath scaffold.
// One decoder issues a single instruction to 256 lockstep cells. Each cell
// owns a 16 x (128-bit payload + 4-bit type) register file and 16 local words.
// This synthesizable subset implements integer/bitwise operations, MAC,
// per-cell SRAM and same-tile 8-neighbor reads. BF16 and GEMM scheduling are
// currently defined by the Python reference model / architecture document.
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
    localparam logic [3:0] DT_I16 = 4'h3;
    localparam logic [3:0] DT_I32 = 4'h4;
    localparam logic [3:0] DT_I64 = 4'h5;
    // 4'hf asks the datapath to inherit the first source's type tag.
    localparam logic [3:0] DT_INHERIT = 4'hf;

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

    assign instruction_ready = 1'b1;

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
                DT_I16: truncate_by_type = {{112{1'b0}}, value[15:0]};
                DT_I32: truncate_by_type = {{96{1'b0}}, value[31:0]};
                DT_I64: truncate_by_type = {{64{1'b0}}, value[63:0]};
                default: truncate_by_type = value;
            endcase
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
            if (dtype == DT_INHERIT)
                lane_dtype[lane] = (opcode == OP_SEL) ? rf_type[lane][src_b] : rf_type[lane][src_a];
            else
                lane_dtype[lane] = dtype;
            neighbor = -1;
            nx = 0;
            ny = 0;

            if (instruction_valid && lane_mask[lane]) begin
                case (opcode)
                    OP_NOP: begin end
                    OP_MOV: begin
                        lane_result[lane] = lane_a[lane];
                        lane_result_type[lane] = rf_type[lane][src_a];
                        lane_write[lane] = 1'b1;
                    end
                    OP_MOVI: begin
                        lane_result[lane] = immediate;
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
                        case (opcode)
                            OP_ADD: lane_result[lane] = signed_a + signed_b;
                            OP_SUB: lane_result[lane] = signed_a - signed_b;
                            OP_MUL: lane_result[lane] = signed_a * signed_b;
                            OP_MAC: lane_result[lane] = lane_acc[lane] + (signed_a * signed_b);
                            OP_AND: lane_result[lane] = lane_a[lane] & lane_b[lane];
                            OP_OR:  lane_result[lane] = lane_a[lane] | lane_b[lane];
                            OP_XOR: lane_result[lane] = lane_a[lane] ^ lane_b[lane];
                            OP_SHL: lane_result[lane] = lane_a[lane] << lane_b[lane][6:0];
                            OP_SHR: lane_result[lane] = signed_a >>> lane_b[lane][6:0];
                            OP_MIN: lane_result[lane] = (signed_min_a < signed_min_b) ? signed_min_a : signed_min_b;
                            OP_MAX: lane_result[lane] = (signed_min_a > signed_min_b) ? signed_min_a : signed_min_b;
                            OP_SEL: lane_result[lane] = (lane_a[lane] != 0) ? lane_b[lane] : lane_c[lane];
                            default: lane_result[lane] = '0;
                        endcase
                        lane_result[lane] = truncate_by_type(lane_result[lane], lane_dtype[lane]);
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
            instruction_done <= instruction_valid;
            if (instruction_valid) begin
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
