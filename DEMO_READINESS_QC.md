# NHIS Comment Intelligence — V9.4 public-demo QC (20 October 2026)

## Current deployment snapshot
- Public, no login, read-only, with **paid OpenAI functionality disabled**.
- 1,693 comment records; 1,693 have saved provisional model-coding records, of which 60 list attachments.
- 65 attachment documents have extraction/transcription status recorded; two include photograph-only content. Original materials must still be checked before quoting or describing coverage as verified.
- Keyword themes and AI theme assignments are **not independently human validated**. The 1,333 near-duplicate/form-letter records affect frequency interpretation. Published AI theme-frequency charts intentionally remain withheld.
- Public website: https://nhis-comment-demo-production.up.railway.app
- Public source repository: https://github.com/HHS-NHIS/NHIS_COMMENT_DEMO

## V9.4 corrections
1. Removed leftover password-gate and paid-API wording from the public interface.
2. Corrected outdated text claiming only 20/65 attachments had extraction, or that all 60 attachment-bearing comments lacked AI coding.
3. Removed nonfunctional theme-editing and analyst-review controls from the read-only comment detail dialog. The original local analyst edition can still edit.
4. Clarified evidence-only operation and preliminary classification warnings.
5. Repackaged the local SQLite database from the exact compressed snapshot used for Docker/Railway, eliminating a local WAL-mode mismatch.
6. Added public-demo endpoint and deployment-mode tests.

## Verification performed
- `python -m unittest discover -s tests -q`: **173 tests passed**.
- `node --check app/app.js`: passed.
- `python scripts/verify_dashboard.py`: passed, with 1,693 unique IDs and zero orphan attachment/tag rows.
- Hosted-mode HTTP smoke tests: `/`, JavaScript and CSS, `/api/meta`, `/api/themes`, `/api/qc`, `/api/source`, `/api/comments`, individual comment details, `/api/semantic/status`, review and assignment CSVs, standard CSV export, QC briefing and evidence-only POST all return HTTP 200.
- Edit/draft/paid endpoints return HTTP 403. Wrong-origin evidence POST returns HTTP 400. 24 simultaneous assignment CSV downloads returned identical hashes.
- Public browser automation was attempted but the execution environment blocked localhost navigation. A visual sign-off from a real external browser remains recommended.

## Not certified and not a technical launch blocker
- Agency approval for public hosting of preliminary analysis on Railway/GitHub (not equivalent to code QC).
- Independent human coding / disagreement adjudication / template-based estimates.
- Validity and completeness of manually transcribed / OCR'd attachments relative to original public documents.
- Fresh reconciliation of 1,693 publicly posted indexed records to the docket's submissions-received total.

**Interpretation:** A functioning exploratory demo, not an official CDC finding or a certified statistical estimate.

## V9.5 public wording / Claude Q C (2026-10-20)

Verified three Claude-assisted image-derived attachment texts in the snapshot, corrected README and UI provenance wording, hid consent prompts in public evidence mode with CSS and JavaScript, removed outdated template-QC timeline language while retaining unvalidated-model warning, and updated fresh-clone test instructions. No AI labels or raw data were modified. Note: cluster labels still vary; the public AI-frequency chart remains withheld.
