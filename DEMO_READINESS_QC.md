# NHIS Comment Intelligence — V9.6 public-demo QC (20 October 2026)

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

Verified three Claude-assisted image-derived attachment texts in the snapshot, corrected README and UI provenance wording, hid consent prompts in public evidence mode with CSS and JavaScript, removed outdated template-QC timeline language while retaining unvalidated-model warning, and updated fresh-clone test instructions. No AI labels or raw data were modified. The database consistency test finds identical labels within 53 exact-content groups (710 records), but thematic accuracy remains unvalidated; the public AI-frequency chart remains withheld.

## October 20 V9.6 reproducibility follow-up
- Documented received-submission observations (2,012 on Oct 19; 3,048 reported Oct 20) without equating them with the 1,693 publicly posted/indexed comment records in this snapshot. Live 3,048 value has not been independently verified from this environment.
- Added a deterministic blinded AI-label pilot (477 theme/comment pairs), private answer-key workflow and score --key compatibility; no analyst labels have been collected for this newer sample.
- Added controlled master-to-public snapshot exporter and a seven-step update guide. Public source still excludes the private validation key.
- Added conservative template-decision migration and full-cluster reassembly on changed/new members. This is a code safeguard, not an assertion that all future refreshes are cost-free; changed shared text may require new model work.
- Existing AI counts are unaffected by this release; no new comments were retrieved or classified.

## V9.7 form-letter subject labeling (October 20, 2026)

- Source-based, provisional editorial labels and one-sentence main-request descriptions were added for all **29** near-duplicate form-letter groups in this 1,693-record snapshot (1,333 clustered records).
- The **Corpus QC → Possible form-letter groups** view now lists all 29 groups with labels, requests, representative excerpts, example comment IDs, and counts.
- The **Data & exports → Form-letter clusters (summary)** CSV includes `subject`, `subject_summary`, `subject_source_id`, and `subject_status`; **Comment × form-letter cluster** CSV includes the same fields for each of 1,693 records (singletons explicitly marked not a form-letter group).
- Individual comment detail pages show the group subject and description for clustered records.
- Labels are editable through `form_letter_subjects.json`, separate from the immutable snapshot and 30 thematic categories; labels are not validated subject codes or evidence of organized campaigns.
- Tests cover all 29 labels, the 993/236 leading groups, all 1,693 rows in the member export, database immutability, and hosted-mode API responses. No OpenAI requests or classification updates were made.
