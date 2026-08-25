// Arithmetic Logic Unit (ALU)
module alu #(parameter DATA_WIDTH = 32)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire [DATA_WIDTH-1:0] operand_a,
    input  wire [DATA_WIDTH-1:0] operand_b,
    input  wire [2:0]            alu_op,
    input  wire                  valid_in,
    output reg  [DATA_WIDTH-1:0] result,
    output reg                   zero_flag,
    output reg                   carry_flag,
    output reg                   overflow_flag,
    output reg                   valid_out
);
    localparam ALU_ADD = 3'b000;
    localparam ALU_SUB = 3'b001;
    localparam ALU_AND = 3'b010;
    localparam ALU_OR  = 3'b011;
    localparam ALU_XOR = 3'b100;
    localparam ALU_SHL = 3'b101;
    localparam ALU_SHR = 3'b110;
    localparam ALU_NOT = 3'b111;
    reg [DATA_WIDTH:0] temp_result;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 0; zero_flag <= 0; carry_flag <= 0; overflow_flag <= 0; valid_out <= 0;
        end else begin
            valid_out <= valid_in;
            if (valid_in) begin
                case (alu_op)
                    ALU_ADD: temp_result = {1'b0, operand_a} + {1'b0, operand_b};
                    ALU_SUB: temp_result = {1'b0, operand_a} - {1'b0, operand_b};
                    ALU_AND: temp_result = {1'b0, operand_a & operand_b};
                    ALU_OR:  temp_result = {1'b0, operand_a | operand_b};
                    ALU_XOR: temp_result = {1'b0, operand_a ^ operand_b};
                    ALU_SHL: temp_result = {1'b0, operand_a << operand_b[4:0]};
                    ALU_SHR: temp_result = {1'b0, operand_a >> operand_b[4:0]};
                    ALU_NOT: temp_result = {1'b0, ~operand_a};
                    default: temp_result = 0;
                endcase
                result        <= temp_result[DATA_WIDTH-1:0];
                carry_flag    <= temp_result[DATA_WIDTH];
                zero_flag     <= (temp_result[DATA_WIDTH-1:0] == 0);
                overflow_flag <= (operand_a[DATA_WIDTH-1] == operand_b[DATA_WIDTH-1]) &&
                                 (temp_result[DATA_WIDTH-1] != operand_a[DATA_WIDTH-1]);
            end
        end
    end
endmodule
