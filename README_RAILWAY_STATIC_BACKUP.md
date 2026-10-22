# NHIS V10.6 Railway static management backup

**Staged only.** This branch hosts working GitHub Pages at `docs/index.html` and contains a Dockerfile for an optional Railway static management service.

- Public static content: 3,748 records (aggregated counts), eight management sections, 30 AI topics, 240 precomputed combinations; source references and embedded Word/CSV reports
- No live LLM calls, SQLite master, secret keys, or analysis cache; read-only GET/HEAD only
- Railway start uses Dockerfile and healthcheck `/healthz`; verify `/version` contains `NHIS-V10.6-STATIC-MANAGEMENT-3748`
- This static site is **not** the full ten-tab Python dashboard.
- Do **not** redirect the existing ten-tab Railway service here unless deliberately replacing it. Preferred: use GitHub Pages now, then deploy the full public-safe ten-tab release to the existing service when Railway is stable; deploy this static site as a second service *within the same project* only if needed.
- Current GitHub Pages content remains unchanged.
- Management classifications and summaries are AI-assisted/provisional.
