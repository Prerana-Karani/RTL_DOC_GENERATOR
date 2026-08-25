// SoC Top Module — integrates ALU + FIFO in a processing pipeline
module soc_top #(parameter DATA_WIDTH = 32)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  s_valid,
    input  wire [DATA_WIDTH-1:0] s_data_a,
    input  wire [DATA_WIDTH-1:0] s_data_b,
    input  wire [2:0]            s_opcode,
    output wire                  s_ready,
    output wire                  m_valid,
    output wire [DATA_WIDTH-1:0] m_result,
    input  wire                  m_ready,
    output wire                  result_zero,
    output wire                  result_overflow
);
    wire alu_valid_out;
    wire [DATA_WIDTH-1:0] alu_result;
    wire alu_zero, alu_carry, alu_overflow;
    wire fifo_full, fifo_empty;
    wire [4:0] fifo_count;

    assign s_ready = !fifo_full;
    assign m_valid = !fifo_empty;

    alu #(.DATA_WIDTH(DATA_WIDTH)) u_alu (
        .clk(clk), .rst_n(rst_n),
        .operand_a(s_data_a), .operand_b(s_data_b),
        .alu_op(s_opcode),
        .valid_in(s_valid && s_ready),
        .result(alu_result),
        .zero_flag(alu_zero), .carry_flag(alu_carry),
        .overflow_flag(alu_overflow), .valid_out(alu_valid_out)
    );

    fifo #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(16)) u_result_fifo (
        .clk(clk), .rst_n(rst_n),
        .wr_en(alu_valid_out), .wr_data(alu_result), .full(fifo_full),
        .rd_en(m_ready && !fifo_empty), .rd_data(m_result),
        .empty(fifo_empty), .count(fifo_count)
    );

    assign result_zero     = alu_zero;
    assign result_overflow = alu_overflow;
endmodule
