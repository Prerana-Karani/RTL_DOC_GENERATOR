// Synchronous FIFO Buffer
module fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16,
    parameter ADDR_WIDTH = 4
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    output wire                  full,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  empty,
    output wire [ADDR_WIDTH:0]   count
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH:0] wr_ptr, rd_ptr;
    assign full  = (count == DEPTH);
    assign empty = (count == 0);
    assign count = wr_ptr - rd_ptr;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) wr_ptr <= 0;
        else if (wr_en && !full) begin
            mem[wr_ptr[ADDR_WIDTH-1:0]] <= wr_data;
            wr_ptr <= wr_ptr + 1;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin rd_ptr <= 0; rd_data <= 0; end
        else if (rd_en && !empty) begin
            rd_data <= mem[rd_ptr[ADDR_WIDTH-1:0]];
            rd_ptr  <= rd_ptr + 1;
        end
    end
endmodule
