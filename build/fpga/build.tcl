# Recreate the delivered v5 design. Run with Vivado 2017.4 only.
# No board programming and no writes to the archived golden bitstream.
proc build_main {flow_args} {
    set flow_here [file dirname [file normalize [info script]]]
    set flow_root [file normalize [file join $flow_here ../..]]
    set flow_usage "Usage: vivado -mode batch -source build/fpga/build.tcl -tclargs -ip-repo <ip_repo> ?-output <new-directory>? ?-mode project|bitstream? ?-jobs 2?"
    array set flow_opt [list -ip-repo "" -output [file join $flow_here work] -mode project -jobs 2]
    if {[llength $flow_args] % 2 != 0} { error $flow_usage }
    foreach {flow_key flow_value} $flow_args {
        if {![info exists flow_opt($flow_key)]} { error "Unknown option $flow_key. $flow_usage" }
        set flow_opt($flow_key) $flow_value
    }
    if {$flow_opt(-ip-repo) eq ""} { error $flow_usage }
    if {$flow_opt(-mode) ni {project bitstream}} { error "Mode must be project or bitstream" }
    if {![string is integer -strict $flow_opt(-jobs)] || $flow_opt(-jobs) < 1 || $flow_opt(-jobs) > 32} {
        error "jobs must be an integer from 1 to 32"
    }
    if {[version -short] ne "2017.4"} {
        error "Use Vivado 2017.4; an IP upgrade is a separate, unverified design change"
    }
    if {[llength [get_projects -quiet]] != 0} { error "Start in a fresh Vivado process" }
    set flow_ip [file normalize $flow_opt(-ip-repo)]
    foreach flow_dir {alinx/i2c_extender alinx/ov5640_ip ip/axi_dynclk_v1_0 ip/rgb2dvi_v1_3} {
        if {![file isfile [file join $flow_ip $flow_dir component.xml]]} {
            error "Missing external IP: $flow_dir/component.xml; see src/fpga/readme.md"
        }
    }
    set flow_output [file normalize $flow_opt(-output)]
    if {[file exists $flow_output]} { error "Output already exists; select a new directory: $flow_output" }
    set flow_src [file join $flow_root src/fpga/zhidiao_measure]
    create_project zhitiao_fpga $flow_output -part xc7z020clg400-2
    set_property ip_repo_paths [list $flow_ip] [current_project]
    update_ip_catalog
    foreach flow_vlnv {alinx.com.cn:user:i2c_extender:1.1 www.alinx.com.cn:user:alinx_ov5640:6.4 digilentinc.com:ip:axi_dynclk:1.0 digilentinc.com:ip:rgb2dvi:1.3} {
        if {[llength [get_ipdefs -all -quiet $flow_vlnv]] == 0} { error "Required IP not in catalog: $flow_vlnv" }
    }
    add_files -norecurse [file join $flow_src linux_ov5640.srcs/sources_1/new/zhidiao_measure_core.v]
    update_compile_order -fileset sources_1
    set flow_result [uplevel #0 [list source [file join $flow_src system_bd.tcl]]]
    if {$flow_result eq "1" || $flow_result eq "2"} { error "Delivered BD script failed: $flow_result" }
    foreach flow_cell {zhidiao_measure_core_0 zhidiao_measure_regs zhidiao_measure_status zhidiao_uart_log zhidiao_status_gpio} {
        if {[llength [get_bd_cells -quiet $flow_cell]] != 1} { error "BD missing required cell: $flow_cell" }
    }
    validate_bd_design
    save_bd_design
    set flow_bd [get_files -quiet */system.bd]
    if {[llength $flow_bd] != 1} { error "Expected exactly one system.bd" }
    generate_target all $flow_bd
    set flow_wrapper [make_wrapper -files $flow_bd -top]
    if {[llength $flow_wrapper] == 0} { error "make_wrapper produced no file" }
    add_files -norecurse $flow_wrapper
    set_property top system_wrapper [get_filesets sources_1]
    foreach flow_xdc {system hdmi_out an5642 zhidiao_measure} {
        add_files -fileset constrs_1 -norecurse [file join $flow_src linux_ov5640.srcs/constrs_1/new ${flow_xdc}.xdc]
    }
    update_compile_order -fileset sources_1
    if {$flow_opt(-mode) eq "project"} {
        puts "PROJECT_READY: $flow_output (not synthesized or implemented)"
        return
    }
    launch_runs synth_1 -jobs $flow_opt(-jobs)
    wait_on_run synth_1
    if {[get_property PROGRESS [get_runs synth_1]] ne "100%" ||
        ![string match -nocase "*complete*" [get_property STATUS [get_runs synth_1]]]} {
        error "Synthesis did not complete"
    }
    launch_runs impl_1 -to_step write_bitstream -jobs $flow_opt(-jobs)
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] ne "100%" ||
        ![string match -nocase "*complete*" [get_property STATUS [get_runs impl_1]]]} {
        error "Implementation did not complete"
    }
    open_run impl_1
    file mkdir [file join $flow_output reports]
    report_utilization -file [file join $flow_output reports/utilization.rpt]
    report_timing_summary -file [file join $flow_output reports/timing_summary.rpt] -warn_on_violation
    check_timing -verbose -file [file join $flow_output reports/check_timing.rpt]
    foreach flow_delay {max min} {
        set flow_paths [get_timing_paths -delay_type $flow_delay -max_paths 1]
        if {[llength $flow_paths] == 0} { error "No $flow_delay timing paths; review constraints" }
        if {[get_property SLACK [lindex $flow_paths 0]] < 0} { error "Negative $flow_delay slack; not accepted" }
    }
    if {![file isfile [file join $flow_output zhitiao_fpga.runs/impl_1/system_wrapper.bit]]} {
        error "No generated bitstream"
    }
    puts "BUILD_COMPLETE: $flow_output; review DRC and all timing checks before loading"
}

if {[catch {build_main $argv} flow_error]} {
    puts stderr "BUILD_FAILED: $flow_error"
    exit 1
}
