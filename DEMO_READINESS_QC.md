# NHIS Comment Intelligence — V10.10.1 Readiness and QC

> This is the QC report for the [V10.10.1 release branch](https://github.com/HHS-NHIS/NHIS_COMMENT_DEMO/tree/release/v10-10-1-release-qc-cleanup-20261024), **not** the historical `main` source snapshot. Switch to that release branch before running the versioned checks.


**Date:** October 24, 2026. **Docket:** CDC-2026-1387. **Frozen public API inventory:** 3,748 unique publicly posted/indexed comment IDs as of October 21, 2026. The inventory must not be represented as the total number of comments received.

## Release scope

- **Existing core dashboard and Management Analysis preserved.** Eight management headings, 30 original AI themes, 15 additional topics, five Content request types, Primary/Secondary role screening, form-letter flags, source excerpts, exports, and full-corpus historical reports.
- **Issue Prioritization** remains a separate read-only ledger with 201 issues, 1,464 recommendations and 815 directly cited distinct comment IDs. Quotations and scoring calculations are QC-checked, but interpretive 1–5 scores and category choices have not been independently validated.
- **Corpus QC** retains the frozen older cluster summary: 48 repeated groups covering 2,908 submitted records; the other 840 are singletons (888 original approximate groups).
- **Management Analysis** uses generalized V10.8.2 template links: **45 inferred repeated groups (2,911 submissions) plus 837 singletons = 882 inferred text groups**. Six cross-group links are flagged provisional; the frozen source records remain all 3,748.

## Reproducible technical checks

Use **`python scripts/run_release_qc.py`** from a fresh Python 3.12+ checkout. It expands the chunked public corpus, validates the public dataset, full-text index, report hashes and eight management headings, then runs `test_v107_*`, `test_v108_*`, `test_v1082.py`, `test_v109_*`, `test_v110_*` and `test_v111_*`. Docker performs the same release gate. Do not rely on older 1,693-comment pilot-era tests or documentation.

Automated coverage: 3,748-source integrity; read-only and hosted API restrictions; source-linked evidence and original-theme versus added-topic intersections; management dropdown and export behavior; 45-group clustering checks and reviewer WPHI examples; all 1,464 ledger quotes matching public text (942 comment-body and 522 attachment-text); score arithmetic and issue IDs; current document wording, external-asset absence, and narrow-screen button wrapping.

## Corrections in this maintenance release

1. Replaced outdated 1,693-record README and V9.6 readiness report. Current QA command uses all versioned release gates instead of stale pilot tests.
2. Reconciled the distinct frozen Corpus QC and inferred Management Analysis form-letter definitions in both README and QC documentation.
3. Corrected issue-ledger date/header to the October 21 public posting inventory and standardized ‘publicly posted/indexed’ terminology.
4. Replaced a personal name in a narrative methodology example with source comment IDs, without modifying the underlying public source.
5. Removed the Google Fonts request and related remote-font CSP permissions from the issue-ledger page.
6. Updated the browser version title to V10.10.1 and added responsive wrapping for long management CSV/Word download buttons.
7. Added regression tests to enforce these wording/layout/documentation decisions.

## Not yet certified

- Independent human adjudication of all classification decisions, issue scores and conservative cross-cluster matches.
- Complete live-browser visual sign-off, especially on 390-pixel devices and networks blocking external assets; code-level responsive checks are not a substitute.
- Independent review of underlying source attachments and any OCR for consequential quotations.
- Agency authorization and suitability of the public hosting environment, which is not inferred from a passing software release gate.

**This is an exploratory, provisional analysis of public records, not final findings or a statement of agency policy.**
