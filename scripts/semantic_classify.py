#!/usr/bin/env python3
"""Resumable, source-grounded OpenAI thematic coding of public NHIS comments — form-letter consistent.

This is MODEL CODING, not independent human validation. Keyword screens are kept separate.
No request is sent without --approve-paid-api. Uses only the OPENAI_API_KEY already set locally.

Coding units (V9, "cluster_units_v1"):
  * template    — for each near-duplicate form-letter cluster, the sentences shared by >=50% of its
                  copies are coded ONCE; every copy that actually contains the evidence sentence
                  receives the same label. Identical letters therefore get identical labels.
  * own_text    — sentences a person added to a form letter (>=5 words after dropping sign-offs and
                  names) are coded separately and merged into that person's labels.
  * full_text   — comments that are not form letters are coded whole (long texts split into segments).
  * attachment  — extracted attachment text is coded separately and merged.
Identical units (same normalized text) are coded once and cached, so re-runs are free.

V2 safeguards (cluster_units_v2; v3 adds line-break-robust template matching):
  * copies containing <75% of their template's sentences are coded on their own text, not the template;
  * a template label whose evidence sentence a copy rewords is kept only if >=80% of the quote's words
    occur in one of the copy's own sentences (that sentence becomes the evidence); otherwise dropped;
  * any label whose only evidence lies in known boilerplate (themes.json global_exclusions - e.g. the
    form letter stating that mental-health and chronic-condition questions "would remain") is dropped;
  * optional human template review (--export-template-review / --apply-template-review) confirms or
    rejects each template label once, for every copy.

Typical use (Anaconda Prompt, dashboard folder):
  python scripts\\semantic_classify.py --dry-run                         # free: units, calls, cost estimate
  python scripts\\semantic_classify.py --approve-paid-api                # code only comments lacking current labels
  python scripts\\semantic_classify.py --recode-all --approve-paid-api   # re-code everything consistently
  python scripts\\semantic_classify.py --consistency-report              # free: agreement among identical letters
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import connect, DB_PATH, taxonomy, utc_now, normalize, mask_exclusions
from local_analysis import chat_openai, redact, MODELS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = 'gpt-6-luna'
METHOD = 'cluster_units_v3'
TEMPLATE_MIN_COVERAGE = 0.75   # copy must contain >=75% of its template's sentences to inherit template labels
VARIANT_MIN_CONTAINMENT = 0.8  # reworded evidence: share of quote words found in one sentence of the copy

SCHEMA = '''Return ONLY a JSON object of this shape:
{"results":[{"comment_id":"EXACT_ID","theme_ids":["id1","id2"],"evidence":{"id1":"VERBATIM 4-20 word quote"},"needs_review":false,"note":"brief uncertainty, if any"}]}
Include every input unit exactly once, using its exact ID as comment_id. Only use theme IDs in the supplied taxonomy. Assign a theme ONLY when the writer substantively discusses that issue; do not classify merely because generic docket language mentions it. One unit can have multiple themes. Provide one verbatim quote of 4-20 words per assigned theme, copied exactly from the input. Never invent quotations. Empty theme_ids allowed. Do not cite external context or fabricate counts. Do not echo personally identifying details in notes. If content is unavailable or unclear, set needs_review true.'''

_SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')
_SIGNOFF = re.compile(r'^(sincerely|thank you|thanks|respectfully|regards|best|kind regards|warm regards|warmly|cordially)\b', re.I)


def create_tables(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS semantic_status (
      comment_id TEXT PRIMARY KEY, source_sha TEXT NOT NULL, model TEXT NOT NULL,
      status TEXT NOT NULL, needs_review INTEGER NOT NULL DEFAULT 0,
      note TEXT NOT NULL DEFAULT '', coded_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS semantic_tags (
      comment_id TEXT NOT NULL, theme_id TEXT NOT NULL, model TEXT NOT NULL,
      source_sha TEXT NOT NULL, evidence TEXT NOT NULL, coded_at TEXT NOT NULL,
      PRIMARY KEY (comment_id, theme_id)
    );
    CREATE INDEX IF NOT EXISTS idx_semantic_tags_theme ON semantic_tags(theme_id);
    CREATE TABLE IF NOT EXISTS semantic_parts (
      source_signature TEXT NOT NULL, segment INTEGER NOT NULL, model TEXT NOT NULL,
      source_sha TEXT NOT NULL, tags_json TEXT NOT NULL, needs_review INTEGER NOT NULL,
      note TEXT NOT NULL DEFAULT '', coded_at TEXT NOT NULL,
      PRIMARY KEY(source_signature,segment,model)
    );''')
    cols = {r[1] for r in db.execute('PRAGMA table_info(semantic_status)')}
    if 'coding_method' not in cols:
        db.execute("ALTER TABLE semantic_status ADD COLUMN coding_method TEXT NOT NULL DEFAULT 'per_comment_v0'")
    tcols = {r[1] for r in db.execute('PRAGMA table_info(semantic_tags)')}
    if 'evidence_source' not in tcols:
        db.execute("ALTER TABLE semantic_tags ADD COLUMN evidence_source TEXT NOT NULL DEFAULT 'full_text'")
    db.commit()


def sentences(text):
    return [s.strip() for s in _SPLIT.split(text or '') if s.strip()]


def skey(s):
    return re.sub(r'[^a-z0-9]+', ' ', s.casefold()).strip()


def sig(text):
    return hashlib.sha256(skey(text).encode('utf8')).hexdigest()


def full_texts(db):
    attachments = {}
    for row in db.execute("SELECT comment_id, GROUP_CONCAT(text, '\n\n') AS txt FROM attachment_text WHERE status='ok' GROUP BY comment_id"):
        attachments[row['comment_id']] = row['txt'] or ''
    docs = Counter(r['comment_id'] for r in db.execute('SELECT DISTINCT comment_id,attachment_id FROM attachments'))
    resolved = Counter(r['comment_id'] for r in db.execute(
        "SELECT comment_id FROM attachment_text WHERE status IN ('ok','no_text')"))
    for r in db.execute('SELECT comment_id, plain_text FROM comments ORDER BY comment_id'):
        cid = r['comment_id']; body = r['plain_text'] or ''; att = attachments.get(cid, '')
        text = body + ('\n\n[EXTRACTED ATTACHMENT]\n' + att if att else '')
        full = docs[cid] == 0 or resolved[cid] >= docs[cid]
        yield {'id': cid, 'body': body, 'attachment': att, 'text': text,
               'sha': hashlib.sha256(text.encode('utf8')).hexdigest(),
               'complete_attachment': full, 'missing_docs': max(0, docs[cid] - resolved[cid]),
               'group_sig': hashlib.sha256(normalize(text).encode('utf8')).hexdigest()}


def pending(db, model, recode_all=False):
    has_method = 'coding_method' in {r[1] for r in db.execute('PRAGMA table_info(semantic_status)')}
    cols = 'comment_id,source_sha,model,status' + (',coding_method' if has_method else '')
    existing = {r['comment_id']: r for r in db.execute(f'SELECT {cols} FROM semantic_status')}
    for obj in full_texts(db):
        rec = existing.get(obj['id'])
        current = (rec and rec['source_sha'] == obj['sha'] and rec['model'] == model
                   and rec['status'] in ('ok', 'partial_attachment')
                   and (not recode_all or (has_method and rec['coding_method'] == METHOD)))
        if current:
            continue
        yield obj


_PLACEHOLDER = re.compile(r'\[[^\]]{0,400}\]')


def _trigrams(text):
    w = skey(text).split()
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def _mostly_in(sentence, grams, threshold=0.8):
    """True when a copy's sentence is just a re-split/truncated fragment of the template (not added text)."""
    g = _trigrams(sentence)
    return bool(g) and len(g & grams) / len(g) >= threshold


def build_units(db, records):
    """Map each comment to its coding units. Returns (units, comment_units, template_keys)."""
    clusters = defaultdict(list)
    have_clusters = db.execute("SELECT name FROM sqlite_master WHERE name='comment_clusters'").fetchone()
    cmap = {r['comment_id']: r['cluster_id'] for r in db.execute('SELECT comment_id,cluster_id FROM comment_clusters')} if have_clusters else {}
    bodies = {r['comment_id']: r['plain_text'] or '' for r in db.execute('SELECT comment_id,plain_text FROM comments')}
    for cid, cl in cmap.items():
        clusters[cl].append(cid)
    units, comment_units, template_keys, template_cache = {}, {}, {}, {}
    for rec in records:
        cid = rec['id']
        members = sorted(clusters.get(cmap.get(cid, cid), [cid]))
        plan = []
        if len(members) > 1:
            cl = cmap[cid]
            if cl not in template_cache:
                freq = Counter(k for m in members for k in {skey(s) for s in sentences(bodies[m])})
                common = {k for k, v in freq.items() if v >= max(2, 0.5 * len(members)) and len(k.split()) >= 4}
                scored = sorted(members, key=lambda m: (-sum(1 for s in sentences(bodies[m]) if skey(s) in common), m))
                tpl = ' '.join(s for s in sentences(bodies[scored[0]]) if skey(s) in common)
                template_cache[cl] = (tpl, common)
            tpl, common = template_cache[cl]
            template_keys[cid] = common
            # Word-trigram coverage: robust to line breaks/sentence splitting; [bracketed placeholders] are ignored.
            tpl_grams = _trigrams(_PLACEHOLDER.sub(' ', tpl))
            my_grams = _trigrams(rec['body'])
            coverage = len(tpl_grams & my_grams) / len(tpl_grams) if tpl_grams else 0
            if tpl and coverage >= TEMPLATE_MIN_COVERAGE:
                plan.append(('template', tpl))
                own = [s for s in sentences(rec['body']) if skey(s) not in common and not _SIGNOFF.match(s)
                       and len(skey(s).split()) > 4 and not _mostly_in(s, tpl_grams)]
                if len(' '.join(own).split()) >= 5:
                    plan.append(('own_text', ' '.join(own)))
            elif rec['body'].strip():
                plan.append(('full_text', rec['body']))   # does not really follow the template: code it on its own
        elif rec['body'].strip():
            plan.append(('full_text', rec['body']))
        if rec['attachment'].strip():
            plan.append(('attachment', rec['attachment']))
        ids = []
        for kind, text in plan:
            u = 'u' + sig(kind + '|' + text)[:20]
            units.setdefault(u, {'id': u, 'kind': kind, 'text': text, 'sha': sig(kind + '|' + text)})
            ids.append(u)
        comment_units[cid] = ids
    return units, comment_units, template_keys


def comparable_quote(text):
    """Normalize typographic punctuation strictly for matching; do not mutate evidence."""
    table = str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"', '–': '-', '—': '-', ' ': ' '})
    return re.sub(r'\s+', ' ', text.translate(table)).casefold().strip()


def _norm_id(x):
    return re.sub(r'\s+', '', str(x or '')).strip('[]()"\'').casefold()


def parse_response(raw, batch, valid_themes, strict=False):
    """Validate model output. Results are matched to inputs BY ID (never by position).

    Tolerates repeated IDs (tags merged), unknown IDs (ignored) and omitted IDs (returned via
    the `missing` attribute so the caller can retry them). Raises only if NO valid result exists,
    or, with strict=True, if anything is unexpected.
    """
    m = re.search(r'\{.*\}', raw or '', re.S)
    if not m:
        raise ValueError('No JSON object in model response')
    output = json.loads(m.group())
    values = output.get('results')
    if not isinstance(values, list):
        raise ValueError('Model output must contain results array')
    by = {_norm_id(r['id']): r for r in batch}
    merged, problems = {}, []
    for v in values:
        if not isinstance(v, dict):
            problems.append('malformed_result'); continue
        key = _norm_id(v.get('comment_id'))
        if key not in by and '|' not in key:
            # model dropped a "|partN" suffix: accept only if exactly one input matches the base
            cands = [k for k in by if k.split('|')[0] == key]
            key = cands[0] if len(cands) == 1 else key
        if key not in by:
            problems.append('unexpected_id:' + str(v.get('comment_id'))[:40]); continue
        if key in merged:
            problems.append('duplicate_id:' + str(v.get('comment_id'))[:40])
        rec = by[key]
        tids = v.get('theme_ids', []); quotes = v.get('evidence', {})
        if not isinstance(tids, list) or not isinstance(quotes, dict):
            problems.append('malformed_tags:' + rec['id']); continue
        slot = merged.setdefault(key, {'comment_id': rec['id'], 'tags': {}, 'errors': [], 'needs_review': False, 'note': ''})
        for tid in tids:
            if tid not in valid_themes:
                slot['errors'].append('invalid_theme:' + str(tid)); continue
            quote = str(quotes.get(tid, '') or '').strip().strip('"“”')
            if not (quote and comparable_quote(quote) in comparable_quote(rec['text'])):
                slot['errors'].append('quote_not_in_source:' + tid); continue
            if len(quote.split()) < 4:
                slot['errors'].append('short_quote_review:' + tid)
            slot['tags'].setdefault(tid, quote[:700])
        slot['needs_review'] = slot['needs_review'] or bool(v.get('needs_review'))
        slot['note'] = (slot['note'] + ' ' + str(v.get('note') or '')).strip()
    if strict and (problems or set(merged) != set(by)):
        raise ValueError('Unexpected model output: ' + '; '.join(problems or ['missing ids']))
    if not merged:
        raise ValueError('No valid results in model output (' + '; '.join(problems)[:200] + ')')
    clean = []
    for key, slot in merged.items():
        errors = slot['errors'] + ([p for p in problems if p.startswith('duplicate_id')] and ['duplicate_id_merged'])
        if any(e.startswith(('invalid_theme', 'quote_not_in_source')) for e in slot['errors']):
            errors.append('some_tags_excluded')
        clean.append({'comment_id': slot['comment_id'], 'tags': list(slot['tags'].items()),
                      'needs_review': slot['needs_review'] or bool(errors),
                      'note': ('; '.join(errors) + '; ' + slot['note'])[:800]})
    result = ParsedResults(clean)
    result.missing = [r['id'] for k, r in by.items() if k not in merged]
    result.problems = problems
    return result


class ParsedResults(list):
    missing: list = []
    problems: list = []


def save_batch(db, batch, results, model, method=METHOD):
    src = {r['id']: r for r in batch}; when = utc_now()
    with db:
        for obj in results:
            cid = obj['comment_id']; rec = src[cid]
            db.execute('DELETE FROM semantic_tags WHERE comment_id=?', (cid,))
            status = 'ok' if rec['complete_attachment'] else 'partial_attachment'
            note = ((str(rec['missing_docs']) + ' attachment(s) unavailable. ' if not rec['complete_attachment'] else '') + obj['note'])[:900]
            db.execute('''INSERT OR REPLACE INTO semantic_status(comment_id,source_sha,model,status,needs_review,note,coded_at,coding_method)
                          VALUES(?,?,?,?,?,?,?,?)''',
                       (cid, rec['sha'], model, status, int(obj['needs_review'] or not rec['complete_attachment']), note, when, method))
            db.executemany('''INSERT OR REPLACE INTO semantic_tags(comment_id,theme_id,model,source_sha,evidence,coded_at,evidence_source)
                              VALUES(?,?,?,?,?,?,?)''',
                           [(cid, t[0], model, rec['sha'], t[1], when, t[2] if len(t) > 2 else 'full_text') for t in obj['tags']])


def split_source(text, max_chars=4400, overlap=160):
    """Process the ENTIRE source, including long attachments, rather than silently truncating it."""
    if len(text) <= max_chars:
        return [text]
    out = []; start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind('\n', start + max_chars // 2, end), text.rfind(' ', start + max_chars // 2, end))
            if boundary > start + max_chars // 2:
                end = boundary
        out.append(text[start:end])
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return out


def save_parts(db, batch, parsed, model):
    """Store each parsed result on the unit/segment whose ID it carries (never by list position)."""
    by_id = {j['id']: j for j in batch}
    now = utc_now()
    with db:
        for record in parsed:
            segment = by_id[record['comment_id']]
            db.execute('INSERT OR REPLACE INTO semantic_parts VALUES(?,?,?,?,?,?,?,?)',
                       (segment['group_sig'], segment['segment'], model, segment['parent_sha'],
                        json.dumps(record['tags'], ensure_ascii=False), int(record['needs_review']), record['note'], now))


def heal_cache(db, model, all_units, all_comment_units):
    """Remove cached unit results that cannot belong to their unit (evidence quote absent from the
    unit's own text — symptom of the pre-V9.1 position-based save). Every result saved in the same
    API batch as a misfiled one is also removed (a swapped partner may hold a wrongly EMPTY result).
    Comments assembled from removed units are invalidated so they are re-coded/re-assembled."""
    by_sha = {u['sha']: uid for uid, u in all_units.items()}
    segs_cache = {}
    bad_batches = set()
    for row in db.execute('SELECT source_signature, segment, tags_json, coded_at FROM semantic_parts WHERE model=?', (model,)).fetchall():
        uid = by_sha.get(row['source_signature'])
        if uid is None:
            continue
        segs = segs_cache.setdefault(uid, split_source(all_units[uid]['text']))
        seg_text = segs[row['segment']] if row['segment'] < len(segs) else ''
        if any(comparable_quote(q) not in comparable_quote(seg_text) for _, q in json.loads(row['tags_json'])):
            bad_batches.add(row['coded_at'])
    bad_units = set()
    with db:
        for stamp in bad_batches:
            for row in db.execute('SELECT source_signature FROM semantic_parts WHERE model=? AND coded_at=?', (model, stamp)).fetchall():
                if row['source_signature'] in by_sha:
                    bad_units.add(by_sha[row['source_signature']])
            db.execute('DELETE FROM semantic_parts WHERE model=? AND coded_at=?', (model, stamp))
        affected = [cid for cid, us in all_comment_units.items() if bad_units & set(us)]
        for cid in affected:
            db.execute('DELETE FROM semantic_tags WHERE comment_id=? AND comment_id IN (SELECT comment_id FROM semantic_status WHERE coding_method=?)', (cid, METHOD))
            db.execute('DELETE FROM semantic_status WHERE comment_id=? AND coding_method=?', (cid, METHOD))
    return len(bad_units), len(affected)


def unit_result(db, unit_sig, n_parts, model):
    rows = db.execute('SELECT segment,tags_json,needs_review,note FROM semantic_parts WHERE source_signature=? AND model=? ORDER BY segment',
                      (unit_sig, model)).fetchall()
    if {r['segment'] for r in rows} != set(range(n_parts)):
        return None
    tags = {}; notes = []; needs = False
    for row in rows:
        for tid, quote in json.loads(row['tags_json']):
            tags.setdefault(tid, quote)
        needs = needs or bool(row['needs_review'])
        if row['note'].strip(' ;'):
            notes.append(row['note'][:160])
    return {'tags': tags, 'needs_review': needs, 'note': '; '.join(notes)[:500]}


_WORDS = re.compile(r'[a-z0-9]+')


def _containment(quote, sentence):
    q = _WORDS.findall(quote.casefold()); sw = set(_WORDS.findall(sentence.casefold()))
    return sum(w in sw for w in q) / len(q) if q else 0.0


def extend_pending_to_affected_clusters(db, all_records, pending_records):
    """Reassemble every member when a new/changed copy affects a template's majority text.

    This avoids leaving older copies with labels derived from a superseded version. Existing
    cached model units are reused. Changes in actual template wording may require an API call;
    do not claim such changes are always free.
    """
    if not pending_records:
        return pending_records
    rows=list(db.execute('SELECT comment_id,cluster_id FROM comment_clusters'))
    cluster_by_id={r[0]:r[1] for r in rows}
    affected={cluster_by_id[r['id']] for r in pending_records if r['id'] in cluster_by_id}
    prior={r['id'] for r in pending_records}
    for rec in all_records:
        if rec['id'] not in prior and cluster_by_id.get(rec['id']) in affected:
            pending_records.append(rec)
            prior.add(rec['id'])
    return pending_records


def carry_forward_template_reviews(db, units):
    """Conservatively carry documented reviewer decisions to a slightly changed template.

    Only reviews with stored original template text are eligible; older untraceable rows
    never silently migrate. Added text preserves approvals if their quotation remains.
    Rejections require 98% template similarity. Ambiguous matches stay for human review.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='template_label_review'").fetchone():
        return 0
    cols={r[1] for r in db.execute('PRAGMA table_info(template_label_review)')}
    if 'template_text' not in cols:
        db.execute("ALTER TABLE template_label_review ADD COLUMN template_text TEXT NOT NULL DEFAULT ''")
    if 'example_comment_id' not in cols:
        db.execute("ALTER TABLE template_label_review ADD COLUMN example_comment_id TEXT NOT NULL DEFAULT ''")
    rows=list(db.execute('SELECT * FROM template_label_review'))
    if not rows: return 0
    current_templates={u['sha']:u['text'] for u in units.values() if u['kind']=='template'}
    existing={(r['template_sha'],r['theme_id']) for r in rows}
    migrated=[]
    for sha,text in current_templates.items():
        if any(r['template_sha']==sha for r in rows): continue
        candidates=[]
        for row in rows:
            old=row['template_text']
            if not old: continue
            ratio=SequenceMatcher(None,skey(text),skey(old),autojunk=False).ratio()
            if ratio>=0.94: candidates.append((ratio,row))
        if not candidates: continue
        candidates.sort(key=lambda x:-x[0]); best=candidates[0][0]
        # A tie between unrelated prior templates is not safe to migrate.
        if len({row['template_sha'] for ratio,row in candidates if ratio>=best-0.005})>1: continue
        for similarity,row in candidates:
            if similarity!=best and row['template_sha']!=candidates[0][1]['template_sha']: continue
            tid=row['theme_id'];decision=row['decision'];ev=row['evidence']
            if (sha,tid) in existing: continue
            if decision==1 and (not ev or comparable_quote(ev) not in comparable_quote(text)): continue
            if decision==0 and similarity<0.98: continue
            migrated.append((sha,tid,decision,ev,'auto-carry:'+row['reviewer'],
                ('Tentative migration from '+row['template_sha'][:16]+'; confirm if text changed materially. '+row['note'])[:500],
                utc_now(),text,row['example_comment_id']))
            existing.add((sha,tid))
    if migrated:
        with db:
            db.executemany("INSERT OR IGNORE INTO template_label_review (template_sha,theme_id,decision,evidence,reviewer,note,reviewed_at,template_text,example_comment_id) VALUES(?,?,?,?,?,?,?,?,?)", migrated)
    return len(migrated)


def _template_reviews(db):
    if not db.execute("SELECT name FROM sqlite_master WHERE name='template_label_review'").fetchone():
        return {}
    return {(r['template_sha'], r['theme_id']): (r['decision'], r['evidence']) for r in db.execute('SELECT * FROM template_label_review')}


def assemble(db, rec, unit_ids, units, parts, model, boilerplate=None, reviews=None):
    """Merge unit results into one comment's labels, keeping every label grounded in THIS copy's text."""
    if boilerplate is None:
        boilerplate = taxonomy().get('global_exclusions', [])
    reviews = _template_reviews(db) if reviews is None else reviews
    merged, notes, needs = {}, [], False
    own_text = comparable_quote(rec['text'])
    own_sentences = sentences(rec['text'])
    for u in unit_ids:
        unit = units[u]
        res = unit_result(db, unit['sha'], len(parts[u]), model)
        if res is None:
            return None
        needs = needs or res['needs_review']
        if res['note']:
            notes.append(f"{unit['kind']}: {res['note']}")
        masked_unit = comparable_quote(mask_exclusions(unit['text'], boilerplate))
        tags = dict(res['tags'])
        if unit['kind'] == 'template':
            for (sha, tid), (decision, ev) in reviews.items():
                if sha != unit['sha']:
                    continue
                if decision == 0:
                    if tags.pop(tid, None) is not None:
                        notes.append(f'template_label_rejected_by_reviewer:{tid}')
                elif decision == 1 and ev and comparable_quote(ev) in comparable_quote(unit['text']):
                    if tags.get(tid) != ev:   # reviewer adds a missed theme or supplies better evidence
                        notes.append(f"template_label_{'evidence_set' if tid in tags else 'added'}_by_reviewer:{tid}")
                    tags[tid] = ev
        for tid, quote in tags.items():
            if comparable_quote(quote) not in masked_unit:
                notes.append(f'boilerplate_evidence_dropped:{tid}')
                continue
            source = unit['kind']
            if unit['kind'] == 'template' and comparable_quote(quote) not in own_text:
                best = max(own_sentences, key=lambda x: _containment(quote, x), default='')
                if best and _containment(quote, best) >= VARIANT_MIN_CONTAINMENT:
                    quote, source = ' '.join(best.split()[:60]), 'template_variant'
                else:
                    notes.append(f'template_quote_absent_in_copy:{tid}'); needs = True
                    continue
            merged.setdefault(tid, (tid, quote, source))
    return {'comment_id': rec['id'], 'tags': list(merged.values()), 'needs_review': needs,
            'note': '; '.join(notes)[:800]}


REVIEW_DDL = ("CREATE TABLE IF NOT EXISTS template_label_review (template_sha TEXT NOT NULL, theme_id TEXT NOT NULL, "
              "decision INTEGER NOT NULL, evidence TEXT NOT NULL DEFAULT '', reviewer TEXT NOT NULL DEFAULT '', "
              "note TEXT NOT NULL DEFAULT '', reviewed_at TEXT NOT NULL, "
              "template_text TEXT NOT NULL DEFAULT '', example_comment_id TEXT NOT NULL DEFAULT '', "
              "PRIMARY KEY(template_sha, theme_id))")


def export_template_review(db, model, path):
    """One row per (form-letter template, AI theme) for a human reviewer: decision 1 = keep, 0 = reject.
    Reviewers may add rows for missed themes (decision 1 + a verbatim quote from the template in ai_evidence)."""
    recs = list(full_texts(db)); units, cu, _ = build_units(db, recs)
    copies = Counter(u for us in cu.values() for u in us)
    example = {}
    for cid in sorted(cu):
        for u in cu[cid]:
            example.setdefault(u, cid)
    themes = {t['id']: t for t in taxonomy()['themes']}
    boiler = taxonomy().get('global_exclusions', [])
    rows = []
    for uid, unit in units.items():
        if unit['kind'] != 'template':
            continue
        res = unit_result(db, unit['sha'], len(split_source(unit['text'])), model) or {'tags': {}}
        masked = comparable_quote(mask_exclusions(unit['text'], boiler))
        for tid, quote in sorted(res['tags'].items()):
            rows.append({'template_sha': unit['sha'], 'example_comment_id': example.get(uid, ''),
                         'copies_using_template': copies[uid], 'theme_id': tid,
                         'theme': themes.get(tid, {}).get('name', tid),
                         'theme_definition': themes.get(tid, {}).get('description', ''), 'ai_evidence': quote,
                         'auto_dropped_as_boilerplate': 'YES' if comparable_quote(quote) not in masked else '',
                         'decision': '', 'reviewer': '', 'note': '', 'template_text': unit['text']})
    rows.sort(key=lambda r: (-r['copies_using_template'], r['template_sha'], r['theme_id']))
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['template_sha']); w.writeheader(); w.writerows(rows)
    return len(rows), len({r['template_sha'] for r in rows})


def apply_template_review(db, path):
    db.execute(REVIEW_DDL)
    columns={r[1] for r in db.execute('PRAGMA table_info(template_label_review)')}
    if 'template_text' not in columns:
        db.execute("ALTER TABLE template_label_review ADD COLUMN template_text TEXT NOT NULL DEFAULT ''")
    if 'example_comment_id' not in columns:
        db.execute("ALTER TABLE template_label_review ADD COLUMN example_comment_id TEXT NOT NULL DEFAULT ''")
    valid = {t['id'] for t in taxonomy()['themes']}
    staged, problems = [], []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for i, r in enumerate(csv.DictReader(f), 2):
            d = str(r.get('decision', '')).strip().lower()
            if d in ('', 'u'):
                continue
            if d not in ('0', '1', 'yes', 'no', 'y', 'n'):
                problems.append(f'row {i}: decision must be 1 or 0'); continue
            if r.get('theme_id') not in valid:
                problems.append(f"row {i}: unknown theme {r.get('theme_id')}"); continue
            if not (r.get('reviewer') or '').strip():
                problems.append(f'row {i}: reviewer initials required'); continue
            staged.append((r['template_sha'], r['theme_id'], 1 if d in ('1', 'yes', 'y') else 0,
                           (r.get('ai_evidence') or '').strip(), r['reviewer'].strip(), (r.get('note') or '').strip(), utc_now(),
                           r.get('template_text',''),r.get('example_comment_id','')))
    if problems:
        raise ValueError('Template review not applied: ' + '; '.join(problems[:10]))
    with db:
        db.executemany('''INSERT OR REPLACE INTO template_label_review
               (template_sha,theme_id,decision,evidence,reviewer,note,reviewed_at,template_text,example_comment_id)
               VALUES(?,?,?,?,?,?,?,?,?)''', staged)
        # force re-assembly of every comment (free: uses cached model results)
        db.execute("UPDATE semantic_status SET coding_method='needs_reassembly' WHERE coding_method=?", (METHOD,))
    return len(staged)


def consistency_report(db, out_path=None):
    """Agreement of AI label sets among copies whose text is identical apart from greeting/sign-off lines."""
    tags = defaultdict(set)
    for r in db.execute('SELECT comment_id, theme_id FROM semantic_tags'):
        tags[r[0]].add(r[1])
    coded = {r[0] for r in db.execute("SELECT comment_id FROM semantic_status WHERE status IN ('ok','partial_attachment')")}
    groups = defaultdict(list)
    for r in db.execute('SELECT comment_id, plain_text FROM comments'):
        if r[0] not in coded:
            continue
        # Same rule the coder uses: content sentences (>4 words, not sign-offs). Names/greetings are ignored.
        core_text = ' '.join(skey(s) for s in sentences(r[1]) if not _SIGNOFF.match(s) and len(skey(s).split()) > 4)
        if core_text:
            groups[hashlib.sha256(core_text.encode()).hexdigest()].append(r[0])
    rows = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        sets = Counter(frozenset(tags[i]) for i in ids)
        modal, n_modal = sets.most_common(1)[0]
        rows.append({'group_size': len(ids), 'distinct_label_sets': len(sets), 'agreement_with_modal': round(n_modal / len(ids), 4),
                     'modal_labels': ' | '.join(sorted(modal)), 'example_ids': ' | '.join(sorted(ids)[:5])})
    rows.sort(key=lambda x: -x['group_size'])
    total = sum(r['group_size'] for r in rows)
    agree = sum(r['agreement_with_modal'] * r['group_size'] for r in rows)
    summary = {'identical_text_groups': len(rows), 'records_in_groups': total,
               'records_matching_group_modal_labels': round(agree), 'weighted_agreement': round(agree / total, 4) if total else None,
               'groups_with_inconsistent_labels': sum(1 for r in rows if r['distinct_label_sets'] > 1)}
    if out_path:
        out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['group_size', 'distinct_label_sets', 'agreement_with_modal', 'modal_labels', 'example_ids'])
            w.writeheader(); w.writerows(rows)
    return summary


def export_results(db, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    for name, sql in [
        ('ai_theme_assignments.csv', '''SELECT t.comment_id,t.theme_id,t.model,t.evidence_source,t.evidence,s.status,s.needs_review,s.coding_method,s.note,c.comment_url
                                FROM semantic_tags t JOIN semantic_status s ON t.comment_id=s.comment_id
                                JOIN comments c ON c.comment_id=t.comment_id ORDER BY t.theme_id,t.comment_id'''),
        ('ai_review_queue.csv', '''SELECT s.comment_id,s.status,s.needs_review,s.coding_method,s.note,c.comment_url,substr(c.plain_text,1,1000) AS comment_excerpt
                                 FROM semantic_status s JOIN comments c ON c.comment_id=s.comment_id
                                 WHERE s.needs_review=1 OR s.status!='ok' ORDER BY s.status,s.comment_id'''),
        ('ai_all_comment_status.csv', '''SELECT s.comment_id,s.source_sha,s.model,s.coding_method,s.status,s.needs_review,s.note,c.comment_url
                                  FROM semantic_status s JOIN comments c ON c.comment_id=s.comment_id ORDER BY s.comment_id'''),
        ('ai_theme_counts_UNVALIDATED.csv', '''SELECT t.theme_id,COUNT(*) AS provisional_comment_records,
                                   COUNT(DISTINCT COALESCE(cl.cluster_id,t.comment_id)) AS approximate_text_groups,
                                   SUM(CASE WHEN s.needs_review=1 THEN 1 ELSE 0 END) AS requiring_review,
                                   'UNVALIDATED - NOT A PREVALENCE ESTIMATE' AS warning
                              FROM semantic_tags t JOIN semantic_status s ON s.comment_id=t.comment_id
                              LEFT JOIN comment_clusters cl ON cl.comment_id=t.comment_id
                              GROUP BY t.theme_id ORDER BY provisional_comment_records DESC''')]:
        cur = db.execute(sql)
        fields = [d[0] for d in cur.description]; rows = cur.fetchall()
        with (outdir / name).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f); w.writerow(fields); w.writerows([tuple(r) for r in rows])
    status = Counter(r['status'] for r in db.execute('SELECT status FROM semantic_status'))
    methods = Counter(r[0] for r in db.execute('SELECT coding_method FROM semantic_status'))
    totals = {'coded_comment_records': sum(v for k, v in status.items() if k in ('ok', 'partial_attachment')),
              'status_breakdown': dict(status), 'coding_methods': dict(methods),
              'full_corpus_count': db.execute('SELECT COUNT(*) FROM comments').fetchone()[0],
              'models': sorted({r[0] for r in db.execute('SELECT model FROM semantic_status') if r[0]}),
              'consistency': consistency_report(db, outdir / 'ai_form_letter_consistency.csv'),
              'warning': 'Model labels are not independently human-validated.'}
    (outdir / 'AI_RESULTS_README.json').write_text(json.dumps(totals, indent=2), encoding='utf8')
    return totals


def estimate(jobs, sys_prompt, model, batch_size):
    rate_in, _, rate_out = MODELS[model]
    calls = (len(jobs) + batch_size - 1) // batch_size
    in_tok = calls * (len(sys_prompt) / 3.5 + 120) + sum(len(j['text']) for j in jobs) / 3.5
    out_tok = len(jobs) * 220
    return calls, int(in_tok), int(out_tok), (in_tok * rate_in + out_tok * rate_out) / 1e6


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db', default=str(DB_PATH)); p.add_argument('--model', default=DEFAULT_MODEL)
    p.add_argument('--batch-size', type=int, default=4); p.add_argument('--limit', type=int, default=0)
    p.add_argument('--approve-paid-api', action='store_true'); p.add_argument('--dry-run', action='store_true')
    p.add_argument('--recode-all', action='store_true', help='re-code every comment with the form-letter-consistent method')
    p.add_argument('--include-partial', action='store_true', help='also code comments whose attachments are still missing (flagged partial)')
    p.add_argument('--export-only', action='store_true'); p.add_argument('--consistency-report', action='store_true')
    p.add_argument('--output', default=str(ROOT / 'reports' / 'semantic'))
    p.add_argument('--export-template-review', metavar='CSV', help='write form-letter template labels for human review (free)')
    p.add_argument('--reassemble-only', action='store_true', help='re-assemble from cached results and export; no API calls (free)')
    p.add_argument('--apply-template-review', metavar='CSV', help='load reviewed template decisions; then re-run --recode-all (re-assembly is free)')
    a = p.parse_args(argv)
    if not 1 <= a.batch_size <= 6:
        p.error('batch-size must be from 1 to 6')
    if a.model not in MODELS:
        p.error('Unknown model; choose one of: ' + ', '.join(MODELS))
    with closing(connect(a.db)) as db:
        create_tables(db)
        if a.export_only:
            print(json.dumps(export_results(db, Path(a.output)), indent=2)); return
        if a.export_template_review:
            n, k = export_template_review(db, a.model, a.export_template_review)
            print(f'Wrote {n} label rows for {k} form-letter templates to {a.export_template_review}. '
                  'Fill decision (1 keep / 0 reject) and reviewer initials, then use --apply-template-review.'); return
        if a.apply_template_review:
            n = apply_template_review(db, a.apply_template_review)
            print(f'Applied {n} template decisions. Now run: python scripts\\semantic_classify.py --recode-all --approve-paid-api '
                  '(existing cached units reassemble without API calls; genuinely changed units may cost money).'); return
        if a.consistency_report:
            print(json.dumps(consistency_report(db, Path(a.output) / 'ai_form_letter_consistency.csv'), indent=2)); return
        all_recs = list(full_texts(db))
        all_units, all_cu, _ = build_units(db, all_recs)
        migrated=carry_forward_template_reviews(db, all_units)
        if migrated: print(f'Carried {migrated} traceable template reviewer decisions to updated template wording; check audit notes.')
        healed_units, healed_comments = heal_cache(db, a.model, all_units, all_cu)
        if healed_units:
            print(f'Cache check: removed {healed_units} misfiled unit results; {healed_comments} comments will be re-assembled/re-coded.')
        todo = list(pending(db, a.model, a.recode_all))
        prior_count=len(todo)
        if not a.limit:  # limited smoke tests must not accidentally rewrite the whole cluster
            todo=extend_pending_to_affected_clusters(db, all_recs, todo)
            if len(todo)>prior_count:
                print(f'Cluster-safe refresh: reassemble {len(todo)-prior_count} existing cluster copies alongside new/changed comments.')
        skipped = [r for r in todo if not r['complete_attachment']]
        if not a.include_partial:
            todo = [r for r in todo if r['complete_attachment']]
        if a.limit:
            todo = todo[:a.limit]
        units, comment_units, _ = build_units(db, todo)
        parts = {u: split_source(v['text']) for u, v in units.items()}
        jobs = [{'id': f'{u}|part{ix + 1}', 'text': part, 'group_sig': v['sha'], 'segment': ix, 'parent_sha': v['sha'],
                 'segment_total': len(parts[u]), 'kind': v['kind']}
                for u, v in units.items() for ix, part in enumerate(parts[u])]
        done = {(r['source_signature'], r['segment'], r['model']) for r in
                db.execute('SELECT source_signature,segment,model FROM semantic_parts')}
        outstanding = [j for j in jobs if (j['group_sig'], j['segment'], a.model) not in done]
        themes = taxonomy()['themes']; valid = {t['id'] for t in themes}
        names = '\n'.join(f"{t['id']}: {t['name']}; {t['description']}" for t in themes)
        sys_prompt = 'You are an evidence-grounded coder of public NHIS redesign comments. ' + SCHEMA + '\nCATEGORIES:\n' + names
        calls, tin, tout, usd = estimate(outstanding, sys_prompt, a.model, a.batch_size)
        kinds = Counter(j['kind'] for j in outstanding)
        print(f'Comments to (re)code: {len(todo)} | coding units: {len(units)} | segments not yet coded: {len(outstanding)} {dict(kinds)}')
        print(f'Skipped (attachments still missing; use --include-partial to code anyway): {0 if a.include_partial else len(skipped)}')
        print(f'Estimate for {a.model}: {calls} API calls, ~{tin:,} input + ~{tout:,} output tokens, ~${usd:.2f} (rough; reasoning tokens extra)')
        if a.dry_run:
            return
        if not a.approve_paid_api and not a.reassemble_only:
            p.error('Paid API authorization required: --approve-paid-api')

        boiler = taxonomy().get('global_exclusions', []); reviews = _template_reviews(db)

        def finalize(comment_ids):
            saved = 0
            for rec in todo:
                if rec['id'] not in comment_ids:
                    continue
                res = assemble(db, rec, comment_units[rec['id']], units, parts, a.model, boiler, reviews)
                if res is None:
                    continue
                save_batch(db, [rec], [res], a.model)
                saved += 1
            return saved

        n_cached = finalize({r['id'] for r in todo})  # anything already cached
        if a.reassemble_only:
            print(f'Re-assembled {n_cached} of {len(todo)} comments from cached results (no API calls). '
                  f'{len(todo) - n_cached} still need coding: run with --recode-all --approve-paid-api.')
            print(json.dumps(export_results(db, Path(a.output)), indent=2)); return
        unit_to_comments = defaultdict(set)
        for cid, us in comment_units.items():
            for u in us:
                unit_to_comments[u].add(cid)
        failed_units = []

        def run_batch(batch):
            """One paid call. Short aliases S1..Sn are used in the prompt; results map back by alias."""
            alias = [{**j, 'id': f'S{k + 1}', 'real_id': j['id']} for k, j in enumerate(batch)]
            prompt = ('Independently classify each UNIT. A unit may be a full comment, the shared text of a form letter, '
                      'text a person added to a form letter, an attachment, or one segment of a long text. '
                      'Only label topics substantively present in the supplied unit. Use the unit IDs S1, S2, ... exactly as given, once each.\n\n' +
                      '\n\n'.join(f"COMMENT SEGMENT ID {j['id']} ({j['kind']}; segment {j['segment'] + 1}/{j['segment_total']}):\n{redact(j['text'])}"
                                    for j in alias))
            answer, meta = chat_openai(a.model, sys_prompt, prompt, approved=True)   # API/budget errors propagate and stop the run
            try:
                parsed = parse_response(answer, alias, valid)
            except ValueError as exc:
                return meta, [j['real_id'] for j in alias], str(exc)
            real = {j['id']: j['real_id'] for j in alias}
            for rec in parsed:
                rec['comment_id'] = real[rec['comment_id']]
            save_parts(db, batch, parsed, a.model)
            return meta, [real[m] for m in parsed.missing], '; '.join(parsed.problems)

        by_job = {j['id']: j for j in outstanding}
        spent = 0.0
        for ix in range(0, len(outstanding), a.batch_size):
            batch = outstanding[ix:ix + a.batch_size]
            try:
                meta, missing, problem = run_batch(batch)
                spent += meta.get('estimated_usd', 0.0)
                for jid in missing:                       # retry omitted/unparseable units one at a time
                    meta1, miss1, prob1 = run_batch([by_job[jid]])
                    spent += meta1.get('estimated_usd', 0.0)
                    if miss1:                             # still unusable: record it for human review, keep going
                        j = by_job[jid]
                        save_parts(db, [j], [{'comment_id': jid, 'tags': [], 'needs_review': True,
                                              'note': 'model_output_invalid_after_retry: ' + (prob1 or problem)[:200]}], a.model)
                        failed_units.append(jid)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                print('Stopped safely; cached units and completed comments remain saved. Rerun to resume: ' + str(exc)[:400], file=sys.stderr)
                raise SystemExit(1)
            touched = set().union(*(unit_to_comments[j['id'].split('|')[0]] for j in batch))
            finalize(touched)
            n_done = db.execute('SELECT COUNT(*) FROM semantic_status WHERE coding_method=?', (METHOD,)).fetchone()[0]
            print(f'Segments {min(ix + a.batch_size, len(outstanding))}/{len(outstanding)}; comments on {METHOD}: {n_done}; '
                  f'API estimate so far ${spent:.4f}' + (f'; units needing review after retry: {len(failed_units)}' if failed_units else ''), flush=True)
        finalize({r['id'] for r in todo})
        if not a.include_partial:
            with db:
                for r in skipped:
                    db.execute('''INSERT OR REPLACE INTO semantic_status(comment_id,source_sha,model,status,needs_review,note,coded_at,coding_method)
                                  VALUES(?,?,?,?,?,?,?,?)''', (r['id'], r['sha'], '', 'awaiting_attachment', 1,
                                  f"{r['missing_docs']} attachment(s) without text; not coded.", utc_now(), 'none'))
        print(json.dumps(export_results(db, Path(a.output)), indent=2))


if __name__ == '__main__':
    main()
