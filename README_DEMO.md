# NHIS Comment Intelligence — Public exploratory demo

Publicly posted comment records from CDC-2026-1387, snapshot of 1,693 comments. This is an **unofficial research prototype**, not an official CDC analysis or certified count of positions.

The shared demo is **public, no login required**, and **read-only**. It uses the saved public-comment database and provisional topic coding. No OpenAI API key is deployed, no cloud model calls are enabled, and visitors cannot upload drafts or edit the data.

**Important limitations:** AI topic assignments remain unvalidated by independent analysts; repeated template/form-letter comments dominate record counts; some label variation remains even within major clusters. Text was extracted for 63 of 65 attachment documents using PDF/Word text extraction, OCR, and AI-assisted (Claude) transcription or description of 3 image-only documents; 2 photographs contain no text. Extracted text has not been verified against the originals; verify before quoting. Publicly posted comment records (1,693) are not the same as all received submissions (2,012 reported at prior docket snapshot).

## Local launch
`python app/server.py`, then http://127.0.0.1:8765

## Public Railway deployment
Deploy this repo using Dockerfile. The database is distributed as `data/comments.sqlite3.xz`, expanded during the Docker build. The server uses the SQLite file in immutable read-only mode. Set `NHIS_DEPLOYMENT_MODE=hosted`, `NHIS_PUBLIC_DEMO=1`, `NHIS_READ_ONLY=1`, and `NHIS_PUBLIC_ORIGIN=https://<your-service-domain>`. Railway provides `PORT`. No `DEMO_USER`, `DEMO_PASSWORD`, or `OPENAI_API_KEY` is required or appropriate for this public snapshot.

Security: management edits, draft uploads, paid model calls, and import endpoints are disabled in hosted mode. The public data can be downloaded by visitors; don't treat it as access-controlled.

## Testing a fresh GitHub checkout
The repository intentionally contains the database as compressed `data/sqlite.part*` segments, **not** a ready-to-open `data/comments.sqlite3`. From the repository root, reconstruct it first:

```bash
python -c "import lzma,pathlib; d=pathlib.Path('data'); (d/'comments.sqlite3').write_bytes(lzma.decompress(b''.join(p.read_bytes() for p in sorted(d.glob('sqlite.part*')))))"
python -m unittest discover -s tests
```

Alternatively, the downloadable release ZIP already includes `data/comments.sqlite3` and the full regression suite; run the test-discovery command without reconstruction. The GitHub checkout contains only the public-route tests; the separate release ZIP contains additional core and integration tests.

## Deferred work
Independent analyst review, form-letter prevalence methodology, attachment extraction verification, and governance approval for publication on third-party services. Hosting the public comments on Railway is not equivalent to any agency cloud authorization.
