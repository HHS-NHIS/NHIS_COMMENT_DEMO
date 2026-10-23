# V10.7 management feedback enhancements — **STAGING, NOT DEPLOYED**
Branch: feature/feedback-form-topic-facets-20261023
Archive baseline: archive/v10-6-pre-feedback-20261023 (commit aff9363a30026a3a681440d1436ffc7432447f02)
Frozen corpus: 3,748 public-comment records. Original compressed database, Dockerfile, themes.json, management artifacts and 240 precompiled summaries are unchanged.

## Reviewer decisions and rationale
1. Repeated-letter controls: **All submissions** (default and authoritative submission counts), **one representative per near-duplicate group** (surface distinct arguments without ignoring participation), and **exclude flagged repeated/likely form submissions** (focus unique concerns; caution: customized letters may add evidence). A flag is not proof of coordination. Exact normalized-text repeats and likely related letters are distinguished; not-flagged is not verified unique.
2. Multiple primary topics may be assigned to a comment when the text substantively addresses several. Passing/associational references receive separate secondary or incidental flags. This read-only supplemental layer is **lexical screening, not a validated model classifier**.
3. Start from the **full V10.6 dashboard**. Preserve the ten existing nav entries (the nine original functionality areas plus management synthesis). The new eleventh entry is "Form letters & topics." Do not replace the full app with the management-only static site.

## New controls and behavior
- Management synthesis: repeated-submission view, 15 supplemental topical facets, relevance, four content-request action filters plus unclear (needs staff review). Existing management reporting headings, original provisional AI-theme filters and original 240 source-grounded summaries remain intact.
- Evidence Search and Comment Explorer: same repeated-submission mode; the query-match CSV output follows it.
- Form letters & topics: submission counts before selection, selected-record counts, exact vs likely duplicate flags, personalized-text indicators, filtered source records and links, and CSV.
- Source-grounded **filtered evidence digest**: top screened primary topics with supporting comment IDs, calculated over selected records. This is not an LLM-written policy synthesis and must not be presented as one.
- Management support records additionally include comments expressly supporting individual measures (including WPHI) without implying they support every redesign goal. The legacy precompiled full-corpus narrative is NOT reworded or recalculated. New supplementary record sets/CSV identify this overlay.

## Limits and next validation gate
- Screening rules may miss nonlexical paraphrases or misinterpret scope, intent and association. Do not report their counts as validated agency findings until an analyst reviews samples.
- Exact duplicate means same normalized source text, not verified form-letter origin. The existing five-word-shingle clustering provides "likely" grouping; expanded semantic similarity requires separate model validation.
- Filtering changes record counts and evidence, **not** the original management narrative or original 240 category × theme compilations. A separate, source-grounded offline synthesis for each repeat-submission mode requires an approved substantive review cycle. Never imply the old full-corpus narrative describes only unique comments.
- No paid model requests or content-coding changes were performed. Existing 30 themes remain unchanged; 15 supplemental topics have their own selection UI because changing the base themes would invalidate the precompiled 240-intersection artifact.

## QA completed
- Local 3,338-record database: 8 focused tests passed for the three sample repeated-letter groups (IDs 0050/0053/0054/0061; 0401/0408/0410; 0308/0334/0335), all three form views, sample WPHI items 0414/0428/0518, incidental vs primary, CSV scope, and zero SQLite writes.
- V9.7 baseline suite: 14 focused regression tests passed (7 form-letter labels, 4 release/validation, 3 public routes).
- Modified browser script compiled with JavaScript parser; HTML div and section structure balanced.
- Checked all existing navigation entries and established API route names remain in the feature branch.
- Dockerfile, original management module, theme definitions and 3,748-snapshot manifest are byte-identical to the archived base.
- **GitHub full-corpus technical QC PASS**: [Actions run 40000804195](https://github.com/HHS-NHIS/NHIS_COMMENT_DEMO/actions/runs/40000804195) verified the 3,748 release, compiled all Python code, passed six new facet unit tests, and passed read-only hosted HTTP smoke covering preserved routes, all form modes, management/term filters, WPHI IDs 0414/0428/0518 and filtered CSV alignment. A complete browser-interaction acceptance pass and SME assessment of the new provisional topic/intent labels are still necessary before production use.
- Historical V9.4–V9.7 tests hardcode the obsolete 1,693 count and cannot be applied as-is to V10.6. The full historical suite timed out locally; 14 selected baseline regressions passed. The new smoke explicitly asserts the current 3,748 record count.

## Deployment policy
Do not merge this branch into main or redeploy the existing Railway full dashboard until it passes an isolated staging build, all preserved-export comparisons, management-filter and WPHI regression tests, and a human review of potentially ambiguous primary vs incidental labels. Do not delete/pause the current Railway projects before the new full app is verified.
