# NHIS Comment Intelligence — Public exploratory demo

Publicly posted comment records from CDC-2026-1387, snapshot of 1,693 comments. This is an **unofficial research prototype**, not an official CDC analysis or certified count of positions.

The shared demo is **public, no login required**, and **read-only**. It uses the saved public-comment database and provisional topic coding. No OpenAI API key is deployed, no cloud model calls are enabled, and visitors cannot upload drafts or edit the data.

**Important limitations:** AI topic assignments remain unvalidated by independent analysts; repeated template/form-letter comments dominate record counts; the labels are model-generated and have not been independently checked by human coders. Text edits to a template may warrant separate assessment. Text was extracted for 63 of 65 attachment documents using PDF/Word text extraction, OCR, and AI-assisted (Claude) transcription or description of 3 image-only documents; 2 photographs contain no text. Extracted text has not been verified against the originals; verify before quoting. The snapshot contains 1,693 publicly posted/indexed comment records at extraction time (October 19, 2026). Portal displays reportedly showed 2,012 submissions received on October 19 and 3,048 on October 20; those changing received counts were not independently verified here and must not be treated as current posted-comment totals.

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

## Updating and validating the dataset
- Follow [`UPDATE_WITH_NEW_COMMENTS.md`](UPDATE_WITH_NEW_COMMENTS.md). Import and reclassify on the local **master**, never in the public read-only container.
- `python scripts/make_ai_validation_sample.py --key PRIVATE_SCORING_KEY.csv --coder HUMAN_CODER_SAMPLE_AI_LABELS.csv` generates the blinded comment/theme review and **separate** model-answer key. This snapshot yields 477 review rows for 30 themes; coders must not see the key.
- After independent coding: `python scripts/score_validation.py coded_results.csv --key PRIVATE_SCORING_KEY.csv --out validation_scores.csv`. Eight responses per positive/negative stratum are only a pilot, not publication-grade precision/recall; sparse themes are particularly uncertain.
- `python scripts/build_public_snapshot.py --source data/comments.sqlite3 --output-dir /path/to/new_public_build` copies the database, removes internal working data, and creates compressed `sqlite.part*` chunks without modifying the master. **Never put the private scoring key in GitHub or the public site.**
- The full 1,693-comment dataset has **provisional** AI labels and requires adjudication by analysts before being presented as validated frequency estimates. Public hosting approval is also unresolved.

### Descriptive form-letter group labels

The public **Corpus QC** display and cluster CSVs include provisional source-based **subject** and **main request** descriptions of the form letters. These editorial descriptions are distinct from the 30 AI screening themes and should be checked against the representative comments before final reporting. Edit `form_letter_subjects.json` to revise labels; no recoding or database migration is required.

**V9.7:** All 29 form-letter groups now have editable provisional subject/summary descriptions in `form_letter_subjects.json`, shown under Corpus QC and the two cluster exports. The cluster calculation and AI labels were not changed.
