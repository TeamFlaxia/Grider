// Two-dimensional mesh of lockstep SIMD tiles. Instructions are broadcast to
// every tile; tile-edge registers provide one-cycle eight-neighbor halo reads.
module grider_mesh #(
    parameter integer TILES_X = 2,
    parameter integer TILES_Y = 2,
    parameter integer TILE_W = 16,
    parameter integer TILE_H = 16,
    parameter integer TILE_COUNT = TILES_X * TILES_Y
) (
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic                 instruction_valid,
    output logic                 instruction_ready,
    output logic                 instruction_done,
    input  logic [4:0]           opcode,
    input  logic [3:0]           dst,
    input  logic [3:0]           src_a,
    input  logic [3:0]           src_b,
    input  logic [3:0]           src_c,
    input  logic [127:0]         immediate,
    input  logic [3:0]           dtype,
    input  logic [TILE_W*TILE_H-1:0] lane_mask,
    input  logic                 host_write_enable,
    input  logic                 host_memory_select,
    input  logic [7:0]           host_tile_x,
    input  logic [7:0]           host_tile_y,
    input  logic [7:0]           host_lane,
    input  logic [3:0]           host_index,
    input  logic [127:0]         host_write_data,
    input  logic [3:0]           host_write_type,
    output logic [127:0]         host_read_data,
    output logic [3:0]           host_read_type
);

    wire [TILE_W*132-1:0] halo_north [0:TILE_COUNT-1];
    wire [TILE_W*132-1:0] halo_south [0:TILE_COUNT-1];
    wire [TILE_H*132-1:0] halo_east [0:TILE_COUNT-1];
    wire [TILE_H*132-1:0] halo_west [0:TILE_COUNT-1];
    wire [TILE_W-1:0] halo_north_valid [0:TILE_COUNT-1];
    wire [TILE_W-1:0] halo_south_valid [0:TILE_COUNT-1];
    wire [TILE_H-1:0] halo_east_valid [0:TILE_COUNT-1];
    wire [TILE_H-1:0] halo_west_valid [0:TILE_COUNT-1];
    wire [131:0] halo_north_east [0:TILE_COUNT-1];
    wire [131:0] halo_south_east [0:TILE_COUNT-1];
    wire [131:0] halo_south_west [0:TILE_COUNT-1];
    wire [131:0] halo_north_west [0:TILE_COUNT-1];
    wire halo_north_east_valid [0:TILE_COUNT-1];
    wire halo_south_east_valid [0:TILE_COUNT-1];
    wire halo_south_west_valid [0:TILE_COUNT-1];
    wire halo_north_west_valid [0:TILE_COUNT-1];

    wire [TILE_W*132-1:0] edge_north [0:TILE_COUNT-1];
    wire [TILE_W*132-1:0] edge_south [0:TILE_COUNT-1];
    wire [TILE_H*132-1:0] edge_east [0:TILE_COUNT-1];
    wire [TILE_H*132-1:0] edge_west [0:TILE_COUNT-1];
    wire [131:0] edge_north_east [0:TILE_COUNT-1];
    wire [131:0] edge_south_east [0:TILE_COUNT-1];
    wire [131:0] edge_south_west [0:TILE_COUNT-1];
    wire [131:0] edge_north_west [0:TILE_COUNT-1];
    wire [TILE_COUNT-1:0] tile_ready;
    wire [TILE_COUNT-1:0] tile_done;
    wire [127:0] tile_host_data [0:TILE_COUNT-1];
    wire [3:0] tile_host_type [0:TILE_COUNT-1];
    wire [TILE_COUNT-1:0] tile_host_write;

    genvar tx;
    genvar ty;
    generate
        for (ty = 0; ty < TILES_Y; ty = ty + 1) begin : mesh_row
            for (tx = 0; tx < TILES_X; tx = tx + 1) begin : mesh_col
                localparam integer IDX = ty * TILES_X + tx;
                if (ty > 0) begin : has_north
                    assign halo_north[IDX] = edge_south[IDX-TILES_X];
                    assign halo_north_valid[IDX] = '1;
                end else begin : no_north
                    assign halo_north[IDX] = '0;
                    assign halo_north_valid[IDX] = '0;
                end
                if (ty < TILES_Y-1) begin : has_south
                    assign halo_south[IDX] = edge_north[IDX+TILES_X];
                    assign halo_south_valid[IDX] = '1;
                end else begin : no_south
                    assign halo_south[IDX] = '0;
                    assign halo_south_valid[IDX] = '0;
                end
                if (tx > 0) begin : has_west
                    assign halo_west[IDX] = edge_east[IDX-1];
                    assign halo_west_valid[IDX] = '1;
                end else begin : no_west
                    assign halo_west[IDX] = '0;
                    assign halo_west_valid[IDX] = '0;
                end
                if (tx < TILES_X-1) begin : has_east
                    assign halo_east[IDX] = edge_west[IDX+1];
                    assign halo_east_valid[IDX] = '1;
                end else begin : no_east
                    assign halo_east[IDX] = '0;
                    assign halo_east_valid[IDX] = '0;
                end

                if ((tx > 0) && (ty > 0)) begin : has_nw
                    assign halo_north_west[IDX] = edge_south_east[IDX-TILES_X-1];
                    assign halo_north_west_valid[IDX] = 1'b1;
                end else begin : no_nw
                    assign halo_north_west[IDX] = '0;
                    assign halo_north_west_valid[IDX] = 1'b0;
                end
                if ((tx < TILES_X-1) && (ty > 0)) begin : has_ne
                    assign halo_north_east[IDX] = edge_south_west[IDX-TILES_X+1];
                    assign halo_north_east_valid[IDX] = 1'b1;
                end else begin : no_ne
                    assign halo_north_east[IDX] = '0;
                    assign halo_north_east_valid[IDX] = 1'b0;
                end
                if ((tx > 0) && (ty < TILES_Y-1)) begin : has_sw
                    assign halo_south_west[IDX] = edge_north_east[IDX+TILES_X-1];
                    assign halo_south_west_valid[IDX] = 1'b1;
                end else begin : no_sw
                    assign halo_south_west[IDX] = '0;
                    assign halo_south_west_valid[IDX] = 1'b0;
                end
                if ((tx < TILES_X-1) && (ty < TILES_Y-1)) begin : has_se
                    assign halo_south_east[IDX] = edge_north_west[IDX+TILES_X+1];
                    assign halo_south_east_valid[IDX] = 1'b1;
                end else begin : no_se
                    assign halo_south_east[IDX] = '0;
                    assign halo_south_east_valid[IDX] = 1'b0;
                end

                assign tile_host_write[IDX] = host_write_enable &&
                    (host_tile_x == tx) && (host_tile_y == ty);
                grider_tile #(.TILE_W(TILE_W), .TILE_H(TILE_H), .LANES(TILE_W*TILE_H)) tile (
                    .clk(clk), .rst_n(rst_n),
                    .instruction_valid(instruction_valid),
                    .instruction_ready(tile_ready[IDX]),
                    .instruction_done(tile_done[IDX]),
                    .host_write_enable(tile_host_write[IDX]),
                    .host_memory_select(host_memory_select),
                    .host_lane(host_lane), .host_index(host_index),
                    .host_write_data(host_write_data), .host_write_type(host_write_type),
                    .host_read_data(tile_host_data[IDX]),
                    .host_read_type(tile_host_type[IDX]),
                    .halo_north(halo_north[IDX]), .halo_south(halo_south[IDX]),
                    .halo_east(halo_east[IDX]), .halo_west(halo_west[IDX]),
                    .halo_north_valid(halo_north_valid[IDX]),
                    .halo_south_valid(halo_south_valid[IDX]),
                    .halo_east_valid(halo_east_valid[IDX]),
                    .halo_west_valid(halo_west_valid[IDX]),
                    .halo_north_east(halo_north_east[IDX]),
                    .halo_south_east(halo_south_east[IDX]),
                    .halo_south_west(halo_south_west[IDX]),
                    .halo_north_west(halo_north_west[IDX]),
                    .halo_north_east_valid(halo_north_east_valid[IDX]),
                    .halo_south_east_valid(halo_south_east_valid[IDX]),
                    .halo_south_west_valid(halo_south_west_valid[IDX]),
                    .halo_north_west_valid(halo_north_west_valid[IDX]),
                    .edge_north(edge_north[IDX]), .edge_south(edge_south[IDX]),
                    .edge_east(edge_east[IDX]), .edge_west(edge_west[IDX]),
                    .edge_north_east(edge_north_east[IDX]),
                    .edge_south_east(edge_south_east[IDX]),
                    .edge_south_west(edge_south_west[IDX]),
                    .edge_north_west(edge_north_west[IDX]),
                    .opcode(opcode), .dst(dst), .src_a(src_a), .src_b(src_b),
                    .src_c(src_c), .immediate(immediate), .dtype(dtype),
                    .lane_mask(lane_mask)
                );
            end
        end
    endgenerate

    integer tile_index;
    always_comb begin
        host_read_data = '0;
        host_read_type = 4'h4;
        for (tile_index = 0; tile_index < TILE_COUNT; tile_index = tile_index + 1) begin
            if ((host_tile_y * TILES_X + host_tile_x) == tile_index) begin
                host_read_data = tile_host_data[tile_index];
                host_read_type = tile_host_type[tile_index];
            end
        end
    end

    assign instruction_ready = &tile_ready;
    assign instruction_done = &tile_done;
endmodule
