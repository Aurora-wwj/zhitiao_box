"""Split large files into ordinary ZIPs; rejoin with byte-for-byte verification.

Only reads/writes files. Never executes archive contents or changes the input.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

MIB = 1024 * 1024


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def split_file(source, destination, part_mib=29):
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('Input must be a nonempty file.')
    if type(part_mib) is not int or not 1 <= part_mib <= 29:
        raise ValueError('Part payload must be 1..29 MiB.')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Output directory must be new or empty.')
    size, sha = source.stat().st_size, digest(source)
    payload_size = part_mib * MIB
    count = (size + payload_size - 1) // payload_size
    common = dict(version=1, original_name=source.name, original_size=size,
                  original_sha256=sha, total_parts=count)
    destination.mkdir(parents=True, exist_ok=True)
    written, observed = [], hashlib.sha256()
    with source.open('rb') as stream:
        for index in range(1, count + 1):
            chunk = stream.read(payload_size)
            observed.update(chunk)
            manifest = dict(common, part_index=index, chunk_size=len(chunk),
                            chunk_sha256=hashlib.sha256(chunk).hexdigest())
            path = destination / f'part-{index:04d}.zip'
            with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True))
                archive.writestr('chunk.bin', chunk)
            if path.stat().st_size >= 30 * MIB:
                raise ValueError('Part exceeds the upload size budget.')
            written.append(path)
        if stream.read(1) or observed.hexdigest() != sha:
            raise ValueError('Input changed while splitting; do not use these parts.')
    return written


def _metadata(path):
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != ['chunk.bin', 'manifest.json']:
            raise ValueError('Unexpected part archive contents.')
        if archive.getinfo('manifest.json').file_size > 65536:
            raise ValueError('Oversized manifest.')
        data = json.loads(archive.read('manifest.json'))
        if not isinstance(data, dict):
            raise ValueError('Invalid manifest.')
        for key in ('original_size', 'total_parts', 'part_index', 'chunk_size'):
            if type(data.get(key)) is not int or data[key] <= 0:
                raise ValueError('Invalid manifest integer.')
        for key in ('original_sha256', 'chunk_sha256'):
            value = data.get(key)
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Invalid SHA-256.')
        if (data.get('version') != 1 or not isinstance(data.get('original_name'), str)
                or not data['part_index'] <= data['total_parts']
                or not data['chunk_size'] <= 29 * MIB
                or archive.getinfo('chunk.bin').file_size != data['chunk_size']):
            raise ValueError('Invalid part metadata.')
        return data


def join_files(parts, destination):
    rows = sorted(((Path(p), _metadata(p)) for p in parts), key=lambda row: row[1]['part_index'])
    if not rows:
        raise ValueError('No parts supplied.')
    first = rows[0][1]
    identity = ('version', 'original_name', 'original_size', 'original_sha256', 'total_parts')
    if (len(rows) != first['total_parts']
            or [m['part_index'] for _, m in rows] != list(range(1, len(rows) + 1))
            or any(any(m[k] != first[k] for k in identity) for _, m in rows)):
        raise ValueError('Missing, duplicated, or mixed parts.')
    destination = Path(destination)
    # Exclusive creation protects any existing file, including on failure.
    output = destination.open('xb')
    observed, size = hashlib.sha256(), 0
    try:
        with output:
            for path, meta in rows:
                with zipfile.ZipFile(path) as archive:
                    chunk = archive.read('chunk.bin')
                if len(chunk) != meta['chunk_size'] or hashlib.sha256(chunk).hexdigest() != meta['chunk_sha256']:
                    raise ValueError('Corrupted part payload.')
                output.write(chunk)
                observed.update(chunk)
                size += len(chunk)
            if size != first['original_size'] or observed.hexdigest() != first['original_sha256']:
                raise ValueError('Reassembled file does not match the original.')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    split = commands.add_parser('split')
    split.add_argument('source')
    split.add_argument('--output', required=True)
    split.add_argument('--part-mib', type=int, default=29)
    join = commands.add_parser('join')
    join.add_argument('parts', nargs='+')
    join.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'split':
        result = split_file(args.source, args.output, args.part_mib)
        print(json.dumps({'parts': [str(p) for p in result], 'count': len(result)}, ensure_ascii=True))
    else:
        path = join_files(args.parts, args.output)
        print(json.dumps({'output': str(path), 'sha256': digest(path)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
