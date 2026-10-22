"""Reassemble public V10.6 release archive from source-controlled GitHub text blobs."""
import base64,hashlib,io,lzma,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parts=sorted((ROOT/'payload_parts').glob('part*.b64'))
if len(parts)!=13:raise RuntimeError('Expected 13 public-data parts, got '+str(len(parts)))
encoded=b''.join(p.read_bytes() for p in parts)
if len(encoded)!=8695788:raise RuntimeError('Incomplete public-data payload encoding')
archive=base64.b64decode(encoded,validate=True)
expected='4409a499888b2cfcd40eb335e2cbaa669afd329ba288ad116e4b769dec66b468'
if hashlib.sha256(archive).hexdigest()!=expected:raise RuntimeError('Public archive checksum mismatch')
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:xz') as tar:
    for member in tar.getmembers():
        target=(ROOT/member.name).resolve()
        if not target.is_relative_to(ROOT.resolve()) or not member.isfile():
            raise RuntimeError('Unsafe release archive member: '+member.name)
    tar.extractall(ROOT,filter='data')
compressed=ROOT/'data/comments.sqlite3.xz'
(ROOT/'data/comments.sqlite3').write_bytes(lzma.decompress(compressed.read_bytes()))
print('Verified public source archive, decompressed frozen 3,748-comment database')
