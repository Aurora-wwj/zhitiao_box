#!/bin/sh
# Read-only deployment-file checks. Does not run OpenOCD, MMIO or FPGA loading.
set -eu
sd_root=${1:-/sd}
if [ "$#" -gt 1 ]; then
    echo "Usage: sh check_files.sh [sd-root]" >&2
    exit 2
fi
failures=0
printf 'ZHITIAO_BOARD_FILES_V1\n'
check_file() {
    name=$1
    path=$2
    if [ -f "$path" ] && [ -r "$path" ]; then
        printf '%s\tPRESENT\n' "$name"
    else
        printf '%s\tMISSING\n' "$name"
        failures=$((failures + 1))
    fi
}
openocd="$sd_root/tools/openocd/bin/openocd"
if [ -f "$openocd" ] && [ -x "$openocd" ]; then
    printf 'openocd_executable\tPRESENT\n'
else
    printf 'openocd_executable\tMISSING\n'
    failures=$((failures + 1))
fi
check_file stlink_config "$sd_root/tools/openocd/share/openocd/scripts/interface/stlink.cfg"
check_file stm32g4_config "$sd_root/tools/openocd/share/openocd/scripts/target/stm32g4x.cfg"
image="$sd_root/pl/zhidiao_observe_v5_led.bit"
check_file v5_bitstream "$image"
if [ -f "$image" ] && [ -r "$image" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum < "$image") || actual=unavailable
    elif [ -x /bin/busybox ]; then
        actual=$(/bin/busybox sha256sum < "$image") || actual=unavailable
    else
        actual=unavailable
    fi
    if [ "$actual" = 'fb4d05e6a075bd405ffa14c1d1a6631fa0a42e4833999c0a0f24b92b027118d6  -' ]; then
        printf 'v5_file_sha256\tMATCH\n'
    else
        printf 'v5_file_sha256\tMISMATCH_OR_UNAVAILABLE\n'
        failures=$((failures + 1))
    fi
fi
printf 'hardware_result\tNOT_TESTED\n'
printf 'running_pl_identity\tNOT_VERIFIED\n'
[ "$failures" -eq 0 ]
