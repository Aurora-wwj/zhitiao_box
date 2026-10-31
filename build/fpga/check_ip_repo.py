"""Check lawful external IP inputs against the delivered archive, without executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
NS = {'s': 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'}


def check(ip_repo):
    ip_repo = Path(ip_repo).resolve(strict=True)
    manifest = json.loads((ROOT / 'data/fpga_external_ips.json').read_text())
    count = 0
    for ip in manifest['ips']:
        component = ET.parse(ip_repo / ip['directory'] / 'component.xml').getroot()
        vlnv = ':'.join(component.findtext('s:' + key, namespaces=NS) or ''
                        for key in ('vendor', 'library', 'name', 'version'))
        if vlnv != ip['vlnv']:
            raise ValueError(f"VLNV mismatch: {ip['directory']}")
        for entry in ip['files']:
            path = (ip_repo / entry['path']).resolve(strict=True)
            if not path.is_relative_to(ip_repo):
                raise ValueError(f"IP file escapes repository: {entry['path']}")
            data = path.read_bytes()
            if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError(f"IP content mismatch: {entry['path']}")
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ip_repo', type=Path)
    args = parser.parse_args()
    try:
        count = check(args.ip_repo)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f'IP_CHECK_FAILED: {error}\n')
    print(f'PASS: four matching external VLNVs and {count} delivered files')


if __name__ == '__main__':
    main()
