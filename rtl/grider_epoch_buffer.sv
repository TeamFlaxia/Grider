// Double-buffer and epoch gate for one tile's published state image.
// Moore-neighbor order is N, NE, E, SE, S, SW, W, NW (bit 0 through bit 7).
module grider_epoch_buffer #(
    parameter integer STATE_WIDTH = 132 * 256,
    parameter integer EPOCH_WIDTH = 32
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic                       state_write_valid,
    output logic                       state_write_ready,
    input  logic [STATE_WIDTH-1:0]     state_write_data,
    input  logic [EPOCH_WIDTH-1:0]     state_write_epoch,
    input  logic [7:0]                 required_neighbors,
    input  logic [7:0]                 neighbor_epoch_valid,
    input  logic [8*EPOCH_WIDTH-1:0]   neighbor_epochs,
    output logic [STATE_WIDTH-1:0]     current_state,
    output logic [EPOCH_WIDTH-1:0]     current_epoch,
    output logic [EPOCH_WIDTH-1:0]     published_epoch,
    output logic                       pending,
    output logic                       swap_pulse
);

    logic [STATE_WIDTH-1:0] state_bank0;
    logic [STATE_WIDTH-1:0] state_bank1;
    logic active_bank;
    logic [EPOCH_WIDTH-1:0] pending_epoch;
    logic neighbors_match;
    logic can_swap;
    logic [EPOCH_WIDTH-1:0] next_epoch;
    integer neighbor;

    always_comb begin
        next_epoch = current_epoch + {{(EPOCH_WIDTH-1){1'b0}}, 1'b1};
        state_write_ready = !pending && (state_write_epoch == next_epoch);
        neighbors_match = 1'b1;
        for (neighbor = 0; neighbor < 8; neighbor = neighbor + 1) begin
            if (required_neighbors[neighbor] &&
                (!neighbor_epoch_valid[neighbor] ||
                 (neighbor_epochs[neighbor*EPOCH_WIDTH +: EPOCH_WIDTH] != pending_epoch)))
                neighbors_match = 1'b0;
        end
        can_swap = pending && neighbors_match;
        current_state = active_bank ? state_bank1 : state_bank0;
        published_epoch = pending ? pending_epoch : current_epoch;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_bank0 <= '0;
            state_bank1 <= '0;
            active_bank <= 1'b0;
            current_epoch <= '0;
            pending_epoch <= '0;
            pending <= 1'b0;
            swap_pulse <= 1'b0;
        end else begin
            swap_pulse <= 1'b0;
            if (state_write_valid && state_write_ready) begin
                if (active_bank)
                    state_bank0 <= state_write_data;
                else
                    state_bank1 <= state_write_data;
                pending_epoch <= state_write_epoch;
                pending <= 1'b1;
            end else if (can_swap) begin
                active_bank <= ~active_bank;
                current_epoch <= pending_epoch;
                pending <= 1'b0;
                swap_pulse <= 1'b1;
            end
        end
    end
endmodule
