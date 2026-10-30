// Three-stage elastic signed MAC datapath.
// Latency is three cycles; the initiation interval is one cycle without stalls.
module grider_mac_pipeline #(
    parameter integer OPERAND_WIDTH = 32,
    parameter integer ACC_WIDTH = 64,
    parameter integer PRODUCT_WIDTH = 2 * OPERAND_WIDTH,
    parameter integer RESULT_WIDTH = ACC_WIDTH
) (
    input  logic                          clk,
    input  logic                          rst_n,
    input  logic                          input_valid,
    output logic                          input_ready,
    input  logic signed [OPERAND_WIDTH-1:0] operand_a,
    input  logic signed [OPERAND_WIDTH-1:0] operand_b,
    input  logic signed [ACC_WIDTH-1:0]    accumulator,
    output logic                          output_valid,
    input  logic                          output_ready,
    output logic signed [RESULT_WIDTH-1:0] result
);

    logic valid_stage0;
    logic valid_stage1;
    logic valid_stage2;
    logic ready_stage0;
    logic ready_stage1;
    logic ready_stage2;
    logic signed [OPERAND_WIDTH-1:0] operand_a_stage0;
    logic signed [OPERAND_WIDTH-1:0] operand_b_stage0;
    logic signed [ACC_WIDTH-1:0] accumulator_stage0;
    logic signed [PRODUCT_WIDTH-1:0] product_stage1;
    logic signed [ACC_WIDTH-1:0] accumulator_stage1;
    logic signed [RESULT_WIDTH-1:0] product_extended;
    logic signed [RESULT_WIDTH-1:0] accumulator_extended;
    logic signed [RESULT_WIDTH-1:0] result_stage2;

    assign output_valid = valid_stage2;
    assign result = result_stage2;
    assign ready_stage2 = !valid_stage2 || output_ready;
    assign ready_stage1 = !valid_stage1 || ready_stage2;
    assign ready_stage0 = !valid_stage0 || ready_stage1;
    assign input_ready = ready_stage0;
    assign product_extended =
        {{(RESULT_WIDTH-PRODUCT_WIDTH){product_stage1[PRODUCT_WIDTH-1]}}, product_stage1};
    assign accumulator_extended =
        {{(RESULT_WIDTH-ACC_WIDTH){accumulator_stage1[ACC_WIDTH-1]}}, accumulator_stage1};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_stage0 <= 1'b0;
            valid_stage1 <= 1'b0;
            valid_stage2 <= 1'b0;
            operand_a_stage0 <= '0;
            operand_b_stage0 <= '0;
            accumulator_stage0 <= '0;
            product_stage1 <= '0;
            accumulator_stage1 <= '0;
            result_stage2 <= '0;
        end else begin
            if (ready_stage2) begin
                valid_stage2 <= valid_stage1;
                if (valid_stage1)
                    result_stage2 <= product_extended + accumulator_extended;
            end
            if (ready_stage1) begin
                valid_stage1 <= valid_stage0;
                if (valid_stage0) begin
                    product_stage1 <= $signed(operand_a_stage0) * $signed(operand_b_stage0);
                    accumulator_stage1 <= accumulator_stage0;
                end
            end
            if (ready_stage0) begin
                valid_stage0 <= input_valid;
                if (input_valid) begin
                    operand_a_stage0 <= operand_a;
                    operand_b_stage0 <= operand_b;
                    accumulator_stage0 <= accumulator;
                end
            end
        end
    end
endmodule
