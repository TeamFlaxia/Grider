// Bounded independent instruction queue for one SIMD tile.
// Instantiate one queue per tile; connect issue_* to that tile's decoder.
module grider_tile_issue_queue #(
    parameter integer INSTRUCTION_WIDTH = 409,
    parameter integer EPOCH_WIDTH = 32,
    parameter integer DEPTH = 4,
    parameter integer PC_WIDTH = 32,
    parameter integer PTR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1,
    parameter integer COUNT_WIDTH = $clog2(DEPTH + 1)
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enqueue_valid,
    output logic                         enqueue_ready,
    input  logic [INSTRUCTION_WIDTH-1:0] enqueue_instruction,
    input  logic [EPOCH_WIDTH-1:0]       enqueue_epoch,
    output logic                         issue_valid,
    input  logic                         issue_ready,
    output logic [INSTRUCTION_WIDTH-1:0] issue_instruction,
    output logic [EPOCH_WIDTH-1:0]       issue_epoch,
    output logic [PC_WIDTH-1:0]          program_counter,
    output logic [COUNT_WIDTH-1:0]       queue_count
);

    logic [INSTRUCTION_WIDTH-1:0] instruction_fifo [0:DEPTH-1];
    logic [EPOCH_WIDTH-1:0] epoch_fifo [0:DEPTH-1];
    logic [PTR_WIDTH-1:0] read_pointer;
    logic [PTR_WIDTH-1:0] write_pointer;
    logic enqueue_fire;
    logic issue_fire;

    function automatic logic [PTR_WIDTH-1:0] advance_pointer(
        input logic [PTR_WIDTH-1:0] pointer
    );
        begin
            advance_pointer = (pointer == DEPTH-1) ? '0 : pointer + 1'b1;
        end
    endfunction

    assign issue_valid = (queue_count != 0);
    assign enqueue_ready = (queue_count < DEPTH) || (issue_valid && issue_ready);
    assign issue_instruction = issue_valid ? instruction_fifo[read_pointer] : '0;
    assign issue_epoch = issue_valid ? epoch_fifo[read_pointer] : '0;
    assign enqueue_fire = enqueue_valid && enqueue_ready;
    assign issue_fire = issue_valid && issue_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_pointer <= '0;
            write_pointer <= '0;
            queue_count <= '0;
            program_counter <= '0;
        end else begin
            if (enqueue_fire) begin
                instruction_fifo[write_pointer] <= enqueue_instruction;
                epoch_fifo[write_pointer] <= enqueue_epoch;
                write_pointer <= advance_pointer(write_pointer);
            end
            if (issue_fire) begin
                read_pointer <= advance_pointer(read_pointer);
                program_counter <= program_counter + 1'b1;
            end
            case ({enqueue_fire, issue_fire})
                2'b10: queue_count <= queue_count + 1'b1;
                2'b01: queue_count <= queue_count - 1'b1;
                default: queue_count <= queue_count;
            endcase
        end
    end
endmodule
