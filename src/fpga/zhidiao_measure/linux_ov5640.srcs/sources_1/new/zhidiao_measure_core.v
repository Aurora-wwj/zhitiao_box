`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2026/10/26 23:51:00
// Design Name: 
// Module Name: zhidiao_measure_core
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////
module zhidiao_measure_core (
    input  wire        clk,          // 100 MHz
    input  wire        resetn,       // active-low reset
    input  wire        signal_in,    // STM32 PA1 from M18

    output reg [31:0]  period_ticks,
    output reg [31:0]  high_ticks,
    output reg [31:0]  edge_count,
    output reg         valid
);

    // ============================================================
    // 1. Synchronize asynchronous external signal into PL clock domain
    // ============================================================

    reg sync_ff1;
    reg sync_ff2;
    reg sync_ff2_d;

    wire rising_edge;
    wire falling_edge;

    assign rising_edge  =  sync_ff2 & ~sync_ff2_d;
    assign falling_edge = ~sync_ff2 &  sync_ff2_d;

    always @(posedge clk) begin
        if (!resetn) begin
            sync_ff1   <= 1'b0;
            sync_ff2   <= 1'b0;
            sync_ff2_d <= 1'b0;
        end
        else begin
            sync_ff1   <= signal_in;
            sync_ff2   <= sync_ff1;
            sync_ff2_d <= sync_ff2;
        end
    end


    // ============================================================
    // 2. Free-running 100 MHz timestamp counter
    // ============================================================

    reg [31:0] timestamp;
    reg [31:0] last_rise_timestamp;
    reg [31:0] pending_high_ticks;

    reg        have_falling_edge;

    localparam WAIT_LOW  = 2'd0;
    localparam WAIT_RISE = 2'd1;
    localparam MEASURE   = 2'd2;

    reg [1:0] state;


    // ============================================================
    // 3. Period / high-time measurement
    // ============================================================

    always @(posedge clk) begin
        if (!resetn) begin

            timestamp           <= 32'd0;
            last_rise_timestamp <= 32'd0;
            pending_high_ticks  <= 32'd0;

            period_ticks        <= 32'd0;
            high_ticks          <= 32'd0;
            edge_count          <= 32'd0;

            valid               <= 1'b0;
            have_falling_edge   <= 1'b0;

            state               <= WAIT_LOW;
        end
        else begin

            // 100 MHz free-running timer
            timestamp <= timestamp + 1'b1;

            // Count all detected transitions
            if (rising_edge || falling_edge)
                edge_count <= edge_count + 1'b1;


            case (state)

                // ------------------------------------------------
                // Wait until a real LOW level has been observed.
                // This prevents a fake first measurement if the
                // external signal happens to be HIGH at reset.
                // ------------------------------------------------
                WAIT_LOW: begin
                    if (!sync_ff2)
                        state <= WAIT_RISE;
                end


                // ------------------------------------------------
                // First real rising edge:
                // establish start timestamp.
                // ------------------------------------------------
                WAIT_RISE: begin
                    if (rising_edge) begin
                        last_rise_timestamp <= timestamp;
                        have_falling_edge   <= 1'b0;
                        state               <= MEASURE;
                    end
                end


                // ------------------------------------------------
                // Normal measurement
                // ------------------------------------------------
                MEASURE: begin

                    // Falling edge:
                    // capture HIGH duration.
                    if (falling_edge) begin
                        pending_high_ticks <=
                            timestamp - last_rise_timestamp;

                        have_falling_edge <= 1'b1;
                    end


                    // Next rising edge:
                    // capture one complete period.
                    if (rising_edge) begin

                        if (have_falling_edge) begin
                            period_ticks <=
                                timestamp - last_rise_timestamp;

                            high_ticks <= pending_high_ticks;

                            // Sticky valid:
                            // once we have a complete measurement,
                            // keep valid high until reset.
                            valid <= 1'b1;
                        end

                        // Start next period
                        last_rise_timestamp <= timestamp;
                        have_falling_edge   <= 1'b0;
                    end
                end


                default: begin
                    state <= WAIT_LOW;
                end

            endcase
        end
    end

endmodule