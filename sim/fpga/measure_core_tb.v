`timescale 1ns / 1ps
// Independent behavioral checks of the unmodified delivered RTL at 100 MHz.
module measure_core_tb;
    reg clk = 0;
    reg resetn = 0;
    reg signal_in = 0;
    wire [31:0] period_ticks, high_ticks, edge_count;
    wire valid;
    always #5 clk = ~clk;
    zhidiao_measure_core dut(clk, resetn, signal_in,
                             period_ticks, high_ticks, edge_count, valid);

    task reset_to;
        input level;
        begin
            @(negedge clk); resetn = 0; signal_in = level;
            repeat (4) @(posedge clk);
            #1;
            if (valid || period_ticks || high_ticks || edge_count)
                $fatal(1, "Reset failed to clear outputs");
            @(negedge clk); resetn = 1;
        end
    endtask

    task drive;
        input level;
        input integer cycles;
        begin
            @(negedge clk); signal_in = level;
            repeat (cycles) @(posedge clk);
            #1;
        end
    endtask

    initial begin
        reset_to(0);
        drive(0, 10);
        if (valid || edge_count) $fatal(1, "Constant LOW must not produce a measurement");
        drive(1, 7);
        if (valid) $fatal(1, "One rising edge is not a full cycle");
        drive(0, 13);
        if (valid) $fatal(1, "A falling edge alone is not a full cycle");
        drive(1, 6);
        if (!valid || period_ticks != 20 || high_ticks != 7 || edge_count != 3)
            $fatal(1, "Expected period/high/edges 20/7/3, got %d/%d/%d", period_ticks, high_ticks, edge_count);
        $display("PASS: reset, silence and non-50%% duty full-cycle measurement");

        drive(0, 9);
        drive(1, 6);
        if (!valid || period_ticks != 15 || high_ticks != 6 || edge_count != 5)
            $fatal(1, "Changed period did not update atomically");
        $display("PASS: changed period/high measurement and edge counting");

        drive(1, 50);
        if (!valid || period_ticks != 15 || high_ticks != 6 || edge_count != 5)
            $fatal(1, "Sticky valid / retained data contract changed");
        $display("PASS: stopped input retains data; software freshness is required");

        reset_to(0);
        drive(0, 8);
        @(negedge clk);
        dut.timestamp = 32'hfffffff8;
        dut.edge_count = 32'hfffffffe;
        drive(1, 7);
        drive(0, 13);
        drive(1, 6);
        if (!valid || period_ticks != 20 || high_ticks != 7 || edge_count != 1)
            $fatal(1, "Unsigned timestamp/edge wrap failed");
        $display("PASS: 32-bit timestamp subtraction and edge counter wrap");

        reset_to(1);
        drive(1, 12);
        if (valid) $fatal(1, "Startup HIGH must not immediately assert valid");
        drive(0, 10);
        drive(1, 6);
        if (!valid) $fatal(1, "Startup HIGH did not recover after transitions");
        // This first value can include the synchronizer's reset-to-HIGH edge.
        // It does NOT prove a full pre-existing physical cycle at startup.
        $display("PASS: startup HIGH recovery (first value is not guaranteed to be a full physical cycle)");
        reset_to(0);
        drive(0, 10);
        if (valid || edge_count) $fatal(1, "Second reset did not clear stale data");
        $display("PASS: reset clears sticky measurement and counters");
        $display("ALL RTL CHECKS PASSED");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "Simulation timeout");
    end
endmodule
