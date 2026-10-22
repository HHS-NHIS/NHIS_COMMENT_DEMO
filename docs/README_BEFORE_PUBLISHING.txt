NHIS V10.6 GitHub Pages backup staging directory.

This branch is intentionally separate from main and does NOT modify the Railway app.

To populate the backup, upload only the CONTENTS of NHIS_GITHUB_PAGES_BACKUP_3748_20261022.zip here, preserving reports/ as docs/reports/.
Do not upload any private SQLite database, full comment text CSV, API keys, internal review records, or source ZIP of the Python dashboard.

Publishing requires Settings > Pages > Deploy from a branch > nhis-pages-backup-v106 > /docs > Save.
A Pages site is usually public even when repository is private. Check agency approval before enabling public Pages.

The static site has 8 categories x 30 provisional AI themes (240 combinations), source-linked summaries, and precompiled Word/CSV reports; no backend or live OpenAI calls.
