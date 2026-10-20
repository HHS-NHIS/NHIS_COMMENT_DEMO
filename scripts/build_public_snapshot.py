#!/usr/bin/env python3
"""Build a redacted, reproducible PUBLIC SQLite snapshot without altering the source database.

Usage:
  python scripts/build_public_snapshot.py --source C:/.../master.sqlite3 --output-dir public_build

The exported SQLite is a copy, not the master; all source connections are read-only. Working
caches/reviews/analyst edits are removed; public search schema and aggregated tags remain.
Public release requires separate authorization for hosting; the flag here is only an acknowledgement.
"""
from __future__ import annotations
import argparse, hashlib, json, lzma, sqlite3
from pathlib import Path

PRIVATE_TABLES = ('semantic_parts', 'template_label_review', 'demo_claude_adjudication_audit')
PRIVATE_ROWS = ('imports', 'analyst_reviews', 'manual_overrides')
PART_BYTES = 96 * 1024

def build(source: Path, output_dir: Path):
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    target = output_dir / 'data' / 'comments.sqlite3'
    if not source.is_file(): raise FileNotFoundError(source)
    if source == target: raise ValueError('The public output MUST differ from the source database')
    target.parent.mkdir(parents=True, exist_ok=True)
    src_before = hashlib.sha256(source.read_bytes()).hexdigest()
    src = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Source backup failed integrity check')
        present = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with dst:
            for name in PRIVATE_TABLES:
                if name in present: dst.execute('DROP TABLE "' + name + '"')
            for name in PRIVATE_ROWS:
                if name in present: dst.execute('DELETE FROM "' + name + '"')
            # Preserve empty working-table schemas because the read-only UI uses them for counts.
            if 'meta' in present:
                dst.execute("INSERT OR REPLACE INTO meta(key,val) VALUES('public_snapshot_note',?)",
                            ('Public, read-only snapshot; no internal review or model cache records.',))
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.execute('VACUUM')
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        counts = {'comments':dst.execute('SELECT COUNT(*) FROM comments').fetchone()[0],
                  'semantic_status':dst.execute('SELECT COUNT(*) FROM semantic_status').fetchone()[0],
                  'semantic_tags':dst.execute('SELECT COUNT(*) FROM semantic_tags').fetchone()[0]}
    finally:
        dst.close(); src.close()
    if hashlib.sha256(source.read_bytes()).hexdigest() != src_before:
        raise RuntimeError('Source file changed during public export; stop and investigate')
    pack = lzma.compress(target.read_bytes(), preset=6)
    for old in target.parent.glob('sqlite.part*'): old.unlink()
    for idx in range(0, len(pack), PART_BYTES):
        (target.parent / ('sqlite.part%03d' % (idx // PART_BYTES))).write_bytes(pack[idx:idx + PART_BYTES])
    # Verify assembled data exactly matches the snapshot.
    assert lzma.decompress(b''.join(p.read_bytes() for p in sorted(target.parent.glob('sqlite.part*')))) == target.read_bytes()
    result = {**counts,'snapshot_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'source_sha256_unchanged':src_before,'parts':len(list(target.parent.glob('sqlite.part*'))),
              'public_warning':'Publicly accessible source documents and model labels; agency clearance required.'}
    (output_dir / 'PUBLIC_SNAPSHOT_MANIFEST.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--output-dir',required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(build(a.source,a.output_dir),indent=2))

if __name__=='__main__':main()
