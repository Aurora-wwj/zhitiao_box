"""Build supplied licensed sources in a new directory; never install to a board.

Default target: arm-linux-gnueabihf. --native validates the recipe on the PC;
its executable is not a Zynq artifact. No downloaded source or uploaded ELF runs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
ARCHIVES = {
    'openocd-0.12.0.tar.gz': 'bb367fd19ab96a65ee5b269b60326d9f36bca1c64d9865cc36985d3651aba563',
    'libusb-1.0.30.tar.bz2': 'fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf',
}


def checked_sources():
    sources = ROOT / 'src/third_party/openocd'
    for name, expected in ARCHIVES.items():
        path = sources / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Source archive SHA mismatch: {name}')
    return sources


def elf_info(path):
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:4] != b'\x7fELF' or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise ValueError('Expected an ELF executable')
    endian = '<' if data[5] == 1 else '>'
    machine = struct.unpack_from(endian + 'H', data, 18)[0]
    if data[4] == 1:
        offset = struct.unpack_from(endian + 'I', data, 28)[0]
        flags = struct.unpack_from(endian + 'I', data, 36)[0]
        size, count = struct.unpack_from(endian + 'HH', data, 42)
    else:
        offset = struct.unpack_from(endian + 'Q', data, 32)[0]
        flags = struct.unpack_from(endian + 'I', data, 48)[0]
        size, count = struct.unpack_from(endian + 'HH', data, 54)
    if size < 4 or count == 0 or offset + size * count > len(data):
        raise ValueError('Malformed ELF program headers')
    types = [struct.unpack_from(endian + 'I', data, offset + size * i)[0] for i in range(count)]
    return {'class': 32 if data[4] == 1 else 64, 'machine': machine,
            'static': 2 not in types and 3 not in types, 'arm_hard_float': machine == 40 and bool(flags & 0x400)}


def build(args):
    sources = checked_sources()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new directory')
    host = None if args.native else (args.host or 'arm-linux-gnueabihf')
    prefix = host + '-' if host else ''
    tools = [prefix + name for name in ('gcc', 'ar', 'ranlib')]
    tools += ['make', 'pkg-config', 'sh']
    for name in tools:
        if not shutil.which(name):
            raise ValueError(f'Missing build dependency: {name}')
    compiler = subprocess.check_output([prefix + 'gcc', '-dumpmachine'], text=True, timeout=10).strip()
    if host and compiler != host:
        raise ValueError(f'Compiler target {compiler} differs from requested {host}')
    output.mkdir(parents=True, exist_ok=False)
    source_dir = output / 'sources'
    source_dir.mkdir()
    for name in ARCHIVES:
        with tarfile.open(sources / name) as archive:
            archive.extractall(source_dir, filter='data')
    stage = output / 'libusb-stage'
    package = output / 'package'
    env = dict(os.environ)
    env.update(CC=prefix + 'gcc', AR=prefix + 'ar', RANLIB=prefix + 'ranlib',
               CFLAGS='-O2', CPPFLAGS='', LDFLAGS='', PKG_CONFIG='pkg-config --static',
               PKG_CONFIG_PATH='', PKG_CONFIG_LIBDIR=str(stage / 'lib/pkgconfig'),
               PKG_CONFIG_SYSROOT_DIR='')
    deadline = time.monotonic() + args.timeout_s
    commands = []
    log_path = output / 'build.log'
    with log_path.open('w') as log:
        def run(command, cwd, run_env=env):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Build budget exceeded')
            commands.append(command)
            log.write('\nCOMMAND: ' + json.dumps(command) + '\n')
            log.flush()
            print(f'BUILD: {Path(cwd).name}: {command[0]} {command[1] if len(command) > 1 else ""}', flush=True)
            subprocess.run(command, cwd=cwd, env=run_env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=remaining, check=True)

        usb_build = output / 'libusb-build'
        usb_build.mkdir()
        host_arg = ['--host=' + host] if host else []
        run(['sh', str(source_dir / 'libusb-1.0.30/configure'), '--prefix=' + str(stage),
             '--enable-static', '--disable-shared', '--disable-udev'] + host_arg, usb_build)
        run(['make', '-j' + str(args.jobs)], usb_build)
        run(['make', 'install'], usb_build)
        openocd_build = output / 'openocd-build'
        openocd_build.mkdir()
        openocd_env = dict(env, LDFLAGS='-static -L' + str(stage / 'lib'))
        run(['sh', str(source_dir / 'openocd-0.12.0/configure'), '--prefix=/sd/tools/openocd',
             '--enable-stlink', '--disable-werror', '--disable-doxygen-html', '--disable-doxygen-pdf']
            + host_arg, openocd_build, openocd_env)
        # libtool's -static only affects libtool libraries. -all-static at the
        # make/link stage is needed to remove libc's dynamic interpreter too.
        # Keep it in Automake's flag: jimtcl links with gcc directly and must
        # not inherit libtool-only -all-static through global LDFLAGS.
        static_link = 'AM_LDFLAGS=-all-static'
        run(['make', '-j' + str(args.jobs), static_link], openocd_build, openocd_env)
        run(['make', static_link, 'DESTDIR=' + str(package), 'install'], openocd_build, openocd_env)
    binary = package / 'sd/tools/openocd/bin/openocd'
    info = elf_info(binary)
    if not info['static']:
        raise ValueError('Generated executable is not fully static; inspect build.log')
    if host and (info['class'] != 32 or not info['arm_hard_float']):
        raise ValueError('Generated executable is not ARM32 hard-float')
    scripts = package / 'sd/tools/openocd/share/openocd/scripts'
    for name in ['interface/stlink.cfg', 'target/stm32g4x.cfg']:
        if (scripts / name).read_bytes() != (source_dir / 'openocd-0.12.0/tcl' / name).read_bytes():
            raise ValueError('Installed OpenOCD config differs from source')
    version = None
    if args.native:
        result = subprocess.run([str(binary), '--version'], text=True, capture_output=True, timeout=10, check=True)
        version = (result.stdout + result.stderr).strip()
        if 'Open On-Chip Debugger 0.12.0' not in version:
            raise ValueError('Unexpected native OpenOCD version')
    result = {'mode': 'native-software-check' if args.native else 'arm-cross-build',
              'compiler_target': compiler, 'source_sha256': ARCHIVES, 'elf': info,
              'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'version_output': version, 'board_tested': False, 'commands': commands}
    (output / 'build_result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('BUILD_COMPLETE: ' + str(package))
    print('Native validation only; do not install this executable on Zynq.' if args.native
          else 'New ARM executable; verify its SHA and run board tests before deployment.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--host', default=None)
    mode.add_argument('--native', action='store_true')
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, 33))
    parser.add_argument('--timeout-s', type=int, default=900, metavar='SECONDS',
                        help='total build-command budget, 1..7200 seconds')
    args = parser.parse_args()
    if args.host and not re.fullmatch(r'[A-Za-z0-9_.+-]+', args.host):
        parser.error('Invalid compiler target triple')
    if not 1 <= args.timeout_s <= 7200:
        parser.error('timeout-s must be from 1 to 7200 seconds')
    try:
        build(args)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        parser.exit(1, f'BUILD_FAILED: {error}; preserve the output directory and inspect build.log if created.\n')


if __name__ == '__main__':
    main()
