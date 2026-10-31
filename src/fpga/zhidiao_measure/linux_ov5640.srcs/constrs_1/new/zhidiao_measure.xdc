set_property PACKAGE_PIN M18 [get_ports {zhidiao_gpio_in_tri_i}]
set_property IOSTANDARD LVCMOS33 [get_ports {zhidiao_gpio_in_tri_i}]

set_property PACKAGE_PIN M17 [get_ports zhidiao_uart_rx]
set_property IOSTANDARD LVCMOS33 [get_ports zhidiao_uart_rx]

set_property PACKAGE_PIN J14 [get_ports {zhidiao_status_led[0]}]
set_property PACKAGE_PIN K14 [get_ports {zhidiao_status_led[1]}]
set_property PACKAGE_PIN J18 [get_ports {zhidiao_status_led[2]}]
set_property PACKAGE_PIN H18 [get_ports {zhidiao_status_led[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {zhidiao_status_led[*]}]