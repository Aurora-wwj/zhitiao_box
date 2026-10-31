"""Static POSIX helpers for the board's BusyBox; never sourced from an LLM."""

import math
import shlex


def interval_us(seconds: float) -> int:
    return max(1, math.ceil(seconds * 1_000_000))


def clock_helper(path: str) -> str:
    # /proc/uptime is monotonic and available without date +%N, Python, or awk.
    # Padding and prefixing the fraction avoid shell octal parsing of 008 etc.
    return "CLOCK=" + shlex.quote(path) + r'''
clock_ms() {
    read up rest < "$CLOCK" || exit 72
    case "$up" in *.*) seconds=${up%%.*}; fraction=${up#*.} ;; *) exit 74 ;; esac
    case "$seconds:$fraction" in *[!0123456789:]*|:*|*:) exit 74 ;; esac
    [ "${#seconds}" -le 12 ] && [ "${#fraction}" -le 9 ] || exit 74
    case "$seconds" in 0) ;; 0*) exit 74 ;; esac
    fraction=${fraction}000
    fraction=${fraction%${fraction#???}}
    printf '%u' "$((seconds * 1000 + 1$fraction - 1000))"
}
'''


REGISTER_HELPER = r'''read_reg() {
    raw=$("$BB" devmem "$1" 32) || exit 72
    case "$raw" in 0x*) digits=${raw#0x} ;; *) exit 74 ;; esac
    case "$digits" in ''|*[!0123456789abcdefABCDEF]*) exit 74 ;; esac
    [ "${#digits}" -le 8 ] || exit 74
    printf '%u' "$((raw))"
}
'''
