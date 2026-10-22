# NHIS V10.6 Railway release candidate (NOT LIVE)

Builds from the October 21 public-index freeze: 3,748 publicly posted comments.

- Eight management reporting headings, 30 AI themes, 240 static category/topic intersections.
- Hosted management preview must be explicitly flagged as provisional, not reviewed. No live inference.
- `data/comments.sqlite3.xz` is built from a sanitized snapshot. The Docker build verifies SQLite integrity,
  3,748 FTS entries, management artifact source fingerprint, and report digest before it can run.
- Internal semantic cache and review tables are excluded. No API keys are included.
- Intended existing Railway service only. The historical 1,693-comment files must NOT be reused.

**Important**: This release has NOT been deployed to Railway. The Railway connector requires renewed authorization.
Do not quote management classification counts as validated agency conclusions.
