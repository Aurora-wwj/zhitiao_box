# Control-flow test doubles only; this does not emulate Vivado or validate IP.
set mock_root [file normalize [lindex $argv 0]]
set mock_scenario [lindex $argv 1]
set mock_output [lindex $argv 2]
set mock_ip [lindex $argv 3]
set mock_generated [file join $mock_output generated]
set mock_bd_ready 0
proc version {args} {
    if {$::mock_scenario eq "version"} { return "2025.2" }
    return "2017.4"
}
proc get_projects {args} { return "" }
proc current_project {} { return project }
proc create_project {name folder args} { file mkdir $folder }
proc set_property {args} {}
proc update_ip_catalog {} {}
proc get_ipdefs {args} {
    if {$::mock_scenario eq "missing_ip"} { return "" }
    return ip
}
proc add_files {args} {
    set p [lindex $args end]
    if {![file isfile $p]} { error "Missing mocked input $p" }
}
proc update_compile_order {args} {}
rename source real_source
proc source {path} {
    if {[file tail $path] eq "system_bd.tcl"} {
        set ::mock_bd_ready 1
        if {$::mock_scenario eq "bd_failed"} { return 1 }
        return ""
    }
    return [uplevel 1 [list real_source $path]]
}
proc get_bd_cells {args} {
    if {!$::mock_bd_ready} { error "BD queried before script was sourced" }
    return [lindex $args end]
}
proc validate_bd_design {} {}
proc save_bd_design {} {}
proc get_files {args} { return system.bd }
proc generate_target {args} {}
proc make_wrapper {args} {
    file mkdir $::mock_generated
    set path [file join $::mock_generated system_wrapper.v]
    close [open $path w]
    return $path
}
proc get_filesets {args} { return [lindex $args end] }
proc launch_runs {name args} {
    if {$name eq "impl_1"} {
        set folder [file join $::mock_output zhitiao_fpga.runs/impl_1]
        file mkdir $folder
        close [open [file join $folder system_wrapper.bit] w]
    }
}
proc wait_on_run {args} {}
proc get_runs {args} { return [lindex $args end] }
proc get_property {key obj} {
    if {$key eq "PROGRESS"} {
        if {$::mock_scenario eq "synthesis" && $obj eq "synth_1"} { return "12%" }
        return "100%"
    }
    if {$key eq "SLACK"} {
        if {$::mock_scenario eq "timing"} { return -0.01 }
        return 0.1
    }
    if {$key eq "STATUS"} {
        if {$::mock_scenario eq "implementation" && $obj eq "impl_1"} { return "write_bitstream ERROR" }
        return "Complete!"
    }
    error "Unexpected mocked property $key"
}
proc open_run {args} {}
proc report_utilization {args} {}
proc report_timing_summary {args} {}
proc check_timing {args} {}
proc get_timing_paths {args} { return path }
set argv [list -ip-repo $mock_ip -output $mock_output -mode bitstream]
source [file join $mock_root build/fpga/build.tcl]
