// Two-bank synchronous SRAM with a streaming burst-write DMA port.
// Select the inactive bank on dma_start_bank to overlap transfer with compute.
// Same-bank accesses use fixed compute priority.
module grider_banked_dma #(
    parameter integer DATA_WIDTH = 32,
    parameter integer WORDS = 256,
    parameter integer ADDR_WIDTH = (WORDS > 1) ? $clog2(WORDS) : 1,
    parameter integer COUNT_WIDTH = $clog2(WORDS + 1)
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    dma_start,
    output logic                    dma_start_ready,
    input  logic                    dma_start_bank,
    input  logic [ADDR_WIDTH-1:0]   dma_start_address,
    input  logic [COUNT_WIDTH-1:0]  dma_length,
    input  logic                    dma_data_valid,
    output logic                    dma_data_ready,
    input  logic [DATA_WIDTH-1:0]   dma_data,
    output logic                    dma_busy,
    output logic                    dma_done,
    output logic [COUNT_WIDTH-1:0]  transferred_count,
    input  logic                    compute_enable,
    input  logic                    compute_write,
    input  logic                    compute_bank,
    input  logic [ADDR_WIDTH-1:0]   compute_address,
    input  logic [DATA_WIDTH-1:0]   compute_write_data,
    output logic                    compute_ready,
    output logic                    compute_read_valid,
    output logic [DATA_WIDTH-1:0]   compute_read_data,
    input  logic                    swap_bank,
    output logic                    active_bank
);

    logic [DATA_WIDTH-1:0] bank0 [0:WORDS-1];
    logic [DATA_WIDTH-1:0] bank1 [0:WORDS-1];
    logic dma_bank;
    logic [ADDR_WIDTH-1:0] dma_address;
    logic [COUNT_WIDTH-1:0] dma_remaining;
    logic dma_fire;
    logic compute_fire;

    assign dma_start_ready = !dma_busy && (dma_length != 0) &&
        (($unsigned(dma_start_address) + $unsigned(dma_length)) <= WORDS);
    assign dma_data_ready = dma_busy &&
        !(compute_enable && (compute_bank == dma_bank));
    assign dma_fire = dma_data_valid && dma_data_ready;
    assign compute_ready = !(dma_fire && (dma_bank == compute_bank) && compute_enable);
    assign compute_fire = compute_enable && compute_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dma_busy <= 1'b0;
            dma_done <= 1'b0;
            dma_bank <= 1'b1;
            dma_address <= '0;
            dma_remaining <= '0;
            transferred_count <= '0;
            active_bank <= 1'b0;
            compute_read_valid <= 1'b0;
            compute_read_data <= '0;
        end else begin
            dma_done <= 1'b0;
            compute_read_valid <= 1'b0;
            if (dma_start && dma_start_ready) begin
                dma_busy <= 1'b1;
                dma_bank <= dma_start_bank;
                dma_address <= dma_start_address;
                dma_remaining <= dma_length;
                transferred_count <= '0;
            end else if (swap_bank && !dma_busy) begin
                active_bank <= ~active_bank;
            end

            if (dma_fire) begin
                if (dma_bank)
                    bank1[dma_address] <= dma_data;
                else
                    bank0[dma_address] <= dma_data;
                transferred_count <= transferred_count + 1'b1;
                dma_remaining <= dma_remaining - 1'b1;
                if (dma_remaining == 1) begin
                    dma_busy <= 1'b0;
                    dma_done <= 1'b1;
                end else begin
                    dma_address <= dma_address + 1'b1;
                end
            end

            if (compute_fire) begin
                if (compute_bank) begin
                    if (compute_write)
                        bank1[compute_address] <= compute_write_data;
                    else begin
                        compute_read_data <= bank1[compute_address];
                        compute_read_valid <= 1'b1;
                    end
                end else begin
                    if (compute_write)
                        bank0[compute_address] <= compute_write_data;
                    else begin
                        compute_read_data <= bank0[compute_address];
                        compute_read_valid <= 1'b1;
                    end
                end
            end
        end
    end
endmodule
