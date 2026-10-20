"""Local-first regulations.gov comment dashboard core; only Python standard library.

IMPORTANT: deterministic theme rules are SCREENING, not validated model findings.
"""
from __future__ import annotations
import csv
import html
import hashlib
import io
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
import os as _os
# NHIS_DB_PATH lets tests (and release checks) point the app at a copy instead of the shipped snapshot.
DB_PATH = Path(_os.environ.get("NHIS_DB_PATH") or (ROOT / "data" / "comments.sqlite3"))
SOURCE_CONFIG = ROOT / "SOURCE_FOLDER.txt"
DEFAULT_SOURCE = ""  # Set NHIS_COMMENTS_SOURCE locally; no personal path in shared source.
THEMES_PATH = ROOT / "themes.json"

FIELDS = ["comment_id", "posted_date", "received_date", "title", "first_name", "last_name",
    "organization", "comment_text", "comment_url", "tracking_number", "attachment_count",
    "attachment_urls", "docket_id", "comment_on_id", "submitter_type", "city", "state",
    "country", "document_type", "withdrawn"]
ATT_FIELDS = ["comment_id", "attachment_id", "title", "filename", "format", "download_url", "metadata_json"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS comments (
      comment_id TEXT PRIMARY KEY, posted_date TEXT, received_date TEXT, title TEXT,
      first_name TEXT, last_name TEXT, organization TEXT, comment_text TEXT,
      comment_url TEXT, tracking_number TEXT, attachment_count TEXT,
      attachment_urls TEXT, docket_id TEXT, comment_on_id TEXT, submitter_type TEXT,
      city TEXT, state TEXT, country TEXT, document_type TEXT, withdrawn TEXT,
      normalized_sha TEXT NOT NULL DEFAULT '', plain_text TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS attachments (
      comment_id TEXT, attachment_id TEXT, title TEXT, filename TEXT,
      format TEXT, download_url TEXT, metadata_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_attachment_comment ON attachments(comment_id);
    CREATE TABLE IF NOT EXISTS tags (
      comment_id TEXT NOT NULL, theme_id TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (comment_id, theme_id)
    );
    CREATE INDEX IF NOT EXISTS idx_tags_theme ON tags(theme_id);
    CREATE TABLE IF NOT EXISTS manual_overrides (
      comment_id TEXT NOT NULL, theme_id TEXT NOT NULL, decision INTEGER NOT NULL,
      PRIMARY KEY (comment_id, theme_id)
    );
    CREATE TABLE IF NOT EXISTS analyst_reviews (
      comment_id TEXT PRIMARY KEY, review_status TEXT NOT NULL DEFAULT 'Not reviewed',
      notes TEXT NOT NULL DEFAULT '', updated_utc TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val TEXT);
    CREATE TABLE IF NOT EXISTS imports (
      import_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, row_count INTEGER,
      comment_ids INTEGER, input_sha256 TEXT, mode TEXT, note TEXT
    );
    """)
    if "plain_text" not in {r["name"] for r in db.execute("PRAGMA table_info(comments)")} :
        db.execute("ALTER TABLE comments ADD COLUMN plain_text TEXT NOT NULL DEFAULT ''")
    tag_cols = {r["name"] for r in db.execute("PRAGMA table_info(tags)")}
    if "keyword" not in tag_cols:
        db.execute("ALTER TABLE tags ADD COLUMN keyword TEXT NOT NULL DEFAULT ''")
    if "source" not in tag_cols:
        db.execute("ALTER TABLE tags ADD COLUMN source TEXT NOT NULL DEFAULT 'body'")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS comment_clusters (
      comment_id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, cluster_size INTEGER NOT NULL,
      overlap REAL NOT NULL, novel_words INTEGER NOT NULL, personalized INTEGER NOT NULL,
      unfilled_placeholder INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cluster ON comment_clusters(cluster_id);
    CREATE TABLE IF NOT EXISTS attachment_text (
      comment_id TEXT NOT NULL, attachment_id TEXT NOT NULL, format TEXT, method TEXT,
      status TEXT NOT NULL, chars INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '',
      file_sha256 TEXT NOT NULL DEFAULT '', extracted_utc TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (comment_id, attachment_id)
    );
    """)
    db.commit()
    return db


# --------------------------------------------------------------------------------------------
# Near-duplicate (form-letter) clustering
# --------------------------------------------------------------------------------------------
SHINGLE_WORDS = 5
CLUSTER_OVERLAP = 0.60      # shared shingles / smaller document (template containment)
CLUSTER_MIN_SHARE = 0.25    # shared shingles / larger document (prevents a long letter quoting one paragraph)
PERSONALIZED_MIN_WORDS = 30 # >= this many words of text not in the cluster representative
PLACEHOLDER_RE = re.compile(r"\[(?:share|insert|add|describe|tell|include|your|name|explain)[^\]]{10,400}\]", re.I)


def _shingles(text, k=SHINGLE_WORDS):
    words = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def compute_clusters(records):
    """Deterministic greedy clustering in comment_id order.

    records: iterable of (comment_id, plain_text). A record joins the first-seen representative
    whose 5-word shingles overlap >= CLUSTER_OVERLAP of the smaller document and >= CLUSTER_MIN_SHARE
    of the larger one. Representatives are never re-assigned, so no transitive chaining.
    Returns {comment_id: dict(cluster_id, overlap, novel_words, unfilled_placeholder)} plus sizes.
    """
    from collections import defaultdict
    records = sorted(records, key=lambda r: r[0])
    sh = {cid: _shingles(t) for cid, t in records}
    inverted = defaultdict(list)
    out = {}
    for cid, text in records:
        s = sh[cid]
        best = None
        if len(s) >= 15:
            counts = Counter(rep for x in s for rep in inverted.get(x, ()))
            for rep, n in counts.most_common(5):
                small, large = sorted((len(s), len(sh[rep])))
                if small and n / small >= CLUSTER_OVERLAP and n / large >= CLUSTER_MIN_SHARE:
                    best = (rep, n / small)
                    break
        if best:
            rep, ov = best
            novel = len(s - sh[rep])
        else:
            rep, ov, novel = cid, 1.0, 0
            for x in s:
                inverted[x].append(cid)
        out[cid] = {"cluster_id": rep, "overlap": round(ov, 4), "novel_words": novel,
                    "unfilled_placeholder": 1 if PLACEHOLDER_RE.search(text or "") else 0}
    sizes = Counter(v["cluster_id"] for v in out.values())
    for v in out.values():
        v["cluster_size"] = sizes[v["cluster_id"]]
        v["personalized"] = 1 if v["cluster_size"] > 1 and v["novel_words"] >= PERSONALIZED_MIN_WORDS else 0
    return out


def _write_derived(db):
    """(Re)compute tags and clusters from stored plain_text (+ any extracted attachment text).

    Caller controls the transaction. Never touches manual_overrides or analyst_reviews.
    """
    tax = taxonomy()
    themes = tax["themes"]
    rows = db.execute("SELECT comment_id, plain_text FROM comments ORDER BY comment_id").fetchall()
    att = {}
    for r in db.execute("SELECT comment_id, GROUP_CONCAT(text, '\n\n') t FROM attachment_text WHERE status='ok' GROUP BY comment_id"):
        att[r["comment_id"]] = r["t"] or ""
    tags = []
    for r in rows:
        body = classify_detail(r["plain_text"], themes, tax)
        for theme_id, (excerpt, kw) in body.items():
            tags.append((r["comment_id"], theme_id, excerpt, kw, "body"))
        if att.get(r["comment_id"]):
            for theme_id, (excerpt, kw) in classify_detail(att[r["comment_id"]], themes, tax).items():
                if theme_id not in body:
                    tags.append((r["comment_id"], theme_id, excerpt, kw, "attachment"))
    db.execute("DELETE FROM tags")
    db.executemany("INSERT INTO tags (comment_id,theme_id,evidence,keyword,source) VALUES (?,?,?,?,?)", tags)
    clusters = compute_clusters([(r["comment_id"], r["plain_text"]) for r in rows])
    db.execute("DELETE FROM comment_clusters")
    db.executemany("INSERT INTO comment_clusters VALUES (?,?,?,?,?,?,?)",
                   [(cid, v["cluster_id"], v["cluster_size"], v["overlap"], v["novel_words"], v["personalized"], v["unfilled_placeholder"])
                    for cid, v in clusters.items()])
    # Invalidate FTS explicitly: multiple rebuilds within one second otherwise reuse a stale
    # timestamp-based fingerprint and silently omit newly extracted attachment text.
    db.execute("DELETE FROM meta WHERE key='local_fts_sha256'")
    db.executemany("INSERT OR REPLACE INTO meta(key,val) VALUES(?,?)",
                   [("derivation_version", DERIVATION_VERSION),
                    ("taxonomy_version", str(tax.get("schema_version", "unknown"))),
                    ("derived_at_utc", utc_now())])
    return len(tags)


def rebuild_derived(db):
    """Re-derive plain_text, hashes, tags, clusters from the preserved raw comment_text.

    Used after a cleaning/taxonomy upgrade when the exporter CSV is not at hand. Raw text,
    analyst overrides and analyst notes are untouched.
    """
    rows = db.execute("SELECT comment_id, comment_text FROM comments").fetchall()
    updates = []
    for r in rows:
        plain = as_plain_text(r["comment_text"])
        n = normalize(plain)
        updates.append((plain, hashlib.sha256(n.encode()).hexdigest() if n else "", r["comment_id"]))
    with db:
        db.executemany("UPDATE comments SET plain_text=?, normalized_sha=? WHERE comment_id=?", updates)
        n_tags = _write_derived(db)
    return {"records": len(rows), "tag_assignments": n_tags, "derivation_version": DERIVATION_VERSION}


def ensure_derived_current(db):
    """Cheap check used at server start: rebuild if code/taxonomy changed since last derivation."""
    m = {r["key"]: r["val"] for r in db.execute("SELECT key,val FROM meta WHERE key IN ('derivation_version','taxonomy_version')")}
    n = db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    if n and (m.get("derivation_version") != DERIVATION_VERSION or m.get("taxonomy_version") != str(taxonomy().get("schema_version", "unknown"))):
        return rebuild_derived(db)
    return None


def all_themes():
    return json.loads(THEMES_PATH.read_text(encoding="utf-8"))["themes"]


# Bump whenever as_plain_text, rule matching, taxonomy handling or clustering changes, so
# stored derived fields (plain_text, hashes, tags, clusters, FTS) are rebuilt from raw text.
DERIVATION_VERSION = "v6-20261019"
_INLINE_TAGS = r"(?:span|font|a|abbr|small|big|sub|sup|label)"


def as_plain_text(value):
    """Normalize Regulations.gov HTML for analysis while preserving original comment_text.

    V6 fixes: closing tags (e.g. ``</span>``) were previously left in 17 records; tags are now
    removed BEFORE entity decoding so escaped literal text such as ``&lt;18`` is never treated as
    markup; zero-width characters are dropped.
    """
    value = str(value or "")
    value = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    value = re.sub(r"(?i)</\s*(?:p|div|li|h[1-6]|blockquote|tr)\s*>", "\n", value)
    value = re.sub(r"(?i)<\s*/?\s*" + _INLINE_TAGS + r"\b[^>]*>", " ", value)
    value = re.sub(r"<\s*/?\s*[A-Za-z][^>]*>", "", value)
    for _ in range(2):
        unescaped = html.unescape(value)
        if unescaped == value:
            break
        value = unescaped
    value = value.replace("\xa0", " ")
    value = re.sub("[​‌‍⁠﻿]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" +([,.;:!?])", r"\1", value)
    value = re.sub(r"[ \t]*\n[ \t]*", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def source_folder():
    import os
    selected = os.environ.get('NHIS_COMMENTS_SOURCE', '').strip()
    if not selected and SOURCE_CONFIG.is_file():
        selected = SOURCE_CONFIG.read_text(encoding='utf-8-sig').strip().strip('"')
    choices = []
    if selected:
        choices.append(Path(selected).expanduser())
    choices.extend([ROOT.parent / 'CDC-2026-1387_PUBLIC_COMMENTS',
                    ROOT / 'CDC-2026-1387_PUBLIC_COMMENTS'])
    for candidate in choices:
        if (candidate / 'comments.csv').is_file():
            return candidate
    return Path(selected).expanduser() if selected else choices[0]


def source_status():
    folder = source_folder()
    files = {name:(folder/name).is_file() for name in
             ('comments.csv','attachments.csv','comment_index.json','export_status.json')}
    return {'path':str(folder),'available':files['comments.csv'], 'files':files}


def sync_from_folder(db, folder=None):
    """Read ONLY saved exporter output; never call the API or modify exporter files."""
    folder = Path(folder) if folder is not None else source_folder()
    comments_file = folder / 'comments.csv'
    if not comments_file.is_file():
        raise ValueError('Exporter folder not found or comments.csv missing: '+str(folder))
    # Avoid importing an in-flight partial line if the user syncs during an active export.
    with comments_file.open('rb') as fh:
        fh.seek(0,2)
        if fh.tell() == 0:
            raise ValueError('Source comments.csv is empty')
        fh.seek(-1,2)
        if fh.read(1) not in (b'\n', b'\r'):
            raise ValueError('Source CSV ends with a partial line. Stop the exporter and try again.')
    def read(name):
        f = folder / name
        return f.read_text(encoding='utf-8-sig') if f.exists() else ''
    out = import_data(db,read('comments.csv'),read('attachments.csv'),
                      read('comment_index.json'),read('export_status.json'))
    out['source_folder']=str(folder)
    return out

def normalize(txt):
    return re.sub(r"\s+", " ", str(txt or "").casefold()).strip()


def _phrase_pattern(phrase, case_sensitive=False):
    """Literal phrase -> boundary-aware, whitespace-flexible regex. 're:' prefix = raw regex."""
    phrase = str(phrase)
    if phrase.startswith("re:"):
        return phrase[3:]
    body = re.sub(r"\s+", " ", phrase).strip()
    if not case_sensitive:
        body = body.casefold()
    return r"(?<!\w)" + re.escape(body).replace(r"\ ", r"\s+") + r"(?!\w)"


_PATTERN_CACHE = {}


def _compiled(phrase, case_sensitive=False):
    key = (phrase, case_sensitive)
    if key not in _PATTERN_CACHE:
        _PATTERN_CACHE[key] = re.compile(_phrase_pattern(phrase, case_sensitive), 0 if case_sensitive else re.I)
    return _PATTERN_CACHE[key]


def taxonomy():
    return json.loads(THEMES_PATH.read_text(encoding="utf-8"))


def mask_exclusions(text, exclusions):
    """Blank out excluded boilerplate spans (same length, so offsets into the original survive)."""
    text = str(text or "")
    for phrase in exclusions or []:
        text = _compiled(phrase).sub(lambda m: " " * len(m.group(0)), text)
    return text


def rule_match_detail(text, keywords, exclusions=(), case_sensitive=(), premasked=None):
    """Return (excerpt, keyword) for the first keyword hit outside excluded spans, else None.

    Screening only; never represent as validated semantic classification.
    ``premasked``: text with some exclusions already blanked (same length as ``text``).
    """
    original = str(text or "")
    masked = mask_exclusions(premasked if premasked is not None else original, exclusions)
    lowered = masked.casefold()
    checks = [(k, False) for k in keywords] + [(k, True) for k in case_sensitive]
    for keyword, cs in checks:
        if not keyword.startswith("re:"):
            # Cheap substring prefilter on the first word; the regex below is authoritative.
            needle = keyword.split()[0] if keyword.split() else keyword
            if (needle not in masked) if cs else (needle.casefold() not in lowered):
                continue
        m = _compiled(keyword, cs).search(masked)
        if m:
            start = max(0, m.start() - 85)
            end = min(len(original), m.end() + 125)
            excerpt = ("…" if start else "") + original[start:end].replace("\n", " ").strip() + ("…" if end < len(original) else "")
            return excerpt, keyword
    return None


def rule_match(text, keywords, exclusions=(), case_sensitive=()):
    hit = rule_match_detail(text, keywords, exclusions, case_sensitive)
    return hit[0] if hit else None


def theme_exclusions(theme, tax=None):
    tax = tax or taxonomy()
    return list(tax.get("global_exclusions", [])) + list(theme.get("exclude", []))


def classify_detail(text, themes=None, tax=None):
    tax = tax or taxonomy()
    themes = themes or tax["themes"]
    out = {}
    base = mask_exclusions(text, tax.get("global_exclusions", []))
    for t in themes:
        hit = rule_match_detail(text, t.get("keywords", []), t.get("exclude", []), t.get("keywords_case_sensitive", []), premasked=base)
        if hit:
            out[t["id"]] = hit
    return out


def classify(text, themes=None):
    return {k: v[0] for k, v in classify_detail(text, themes).items()}


def parse_csv(text, required):
    if not text or not text.strip():
        raise ValueError("CSV is empty")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV header is missing")
    fields = {f.strip() for f in reader.fieldnames if f}
    missing = set(required) - fields
    if missing:
        raise ValueError("Missing required CSV columns: " + ", ".join(sorted(missing)))
    return list(reader)


def import_data(db, comments_csv, attachments_csv="", index_json="", status_json="", mode="real", allow_smaller=False):
    """Exact snapshot replacement, transactional. Reimporting full cumulative CSV is idempotent.

    This is intentional: retired / withdrawn comments should not remain stale in counts.
    """
    rows = parse_csv(comments_csv, {"comment_id", "comment_text"})
    if not rows:
        raise ValueError("No comment records found. Refusing to erase current data.")
    prior_count=db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    if prior_count > len(rows) and not allow_smaller:
        raise ValueError(f"Refusing smaller snapshot ({len(rows)} versus {prior_count} stored). Use the complete CSV, or explicitly permit replacing with fewer records.")
    if len(rows) > 1000000:
        raise ValueError("Too many rows for this pilot")
    seen = set()
    payload = []
    for row in rows:
        cid = str(row.get("comment_id", "")).strip()
        if not cid:
            raise ValueError("A comment row has no comment_id. Import cancelled.")
        if cid in seen:
            raise ValueError("Duplicate comment_id in input: " + cid + ". Import cancelled.")
        seen.add(cid)
        d = {k: str(row.get(k) or "") for k in FIELDS}
        d["comment_id"] = cid
        d["plain_text"] = as_plain_text(d["comment_text"])
        d["normalized_sha"] = hashlib.sha256(normalize(d["plain_text"]).encode()).hexdigest() if normalize(d["plain_text"]) else ""
        payload.append(d)
    synthetic_flags = [d["comment_id"].startswith("SYNTHETIC-") for d in payload]
    if any(synthetic_flags):
        if not all(synthetic_flags):
            raise ValueError("Cannot mix SYNTHETIC demo records and real comments in the same corpus")
        mode = "synthetic demo"  # Never allow a test CSV to display as actual public comments.
    # A missing attachment CSV means "not supplied", NOT "delete all attachments".
    # Keep previously imported metadata for surviving IDs, including extracted text records.
    # To replace attachment metadata, supply the complete attachments.csv explicitly.
    attachment_source = 'supplied' if attachments_csv.strip() else 'retained_existing'
    if attachments_csv.strip():
        atts = parse_csv(attachments_csv, {"comment_id"})
        atts = [{k: str(a.get(k) or "") for k in ATT_FIELDS} for a in atts]
    else:
        atts = [{k: str(r[k] or "") for k in ATT_FIELDS} for r in db.execute(
            'SELECT ' + ','.join(ATT_FIELDS) + ' FROM attachments') if r['comment_id'] in seen]
    orphaned = sum(1 for a in atts if a["comment_id"] not in seen)
    if orphaned:
        raise ValueError(f"Attachment CSV has {orphaned} references to comment IDs not in this snapshot")
    index = json.loads(index_json) if index_json.strip() else {}
    status = json.loads(status_json) if status_json.strip() else {}
    if index and not isinstance(index, dict):
        raise ValueError("comment_index.json must contain a JSON object")
    if status and not isinstance(status, dict):
        raise ValueError("export_status.json must contain a JSON object")
    if index.get("ids") is not None:
        if not isinstance(index["ids"], list) or len(set(index["ids"])) != len(index["ids"]):
            raise ValueError("Index must have a list of unique comment IDs")
        unmatched = seen - set(index["ids"])
        if unmatched:
            raise ValueError(f"{len(unmatched)} comment IDs are absent from the supplied index; check you selected matching files")
    # The status 'complete' must not be trusted if the actual rows disagree.
    if status.get("complete_relative_to_index") is True and isinstance(index.get("ids"),list):
        if len(rows) != len(index["ids"]):
            raise ValueError("Status claims complete export but CSV row count differs from index")
    total = index.get("total_reported", status.get("api_total_reported_at_index_time"))
    indexed = len(index["ids"]) if isinstance(index.get("ids"), list) else status.get("indexed_comment_count")
    # If public index exists but is stale or index subset differs, clearly label it as a snapshot.
    comment_sha = hashlib.sha256(comments_csv.encode("utf-8")).hexdigest()
    import_meta = {
        "mode": mode, "imported_at_utc": utc_now(), "records": str(len(payload)),
        "api_total_at_index_time": "" if total is None else str(total),
        "indexed_count": "" if indexed is None else str(indexed),
        "index_retrieved_at_utc": str(index.get("retrieved_at_utc") or ""),
        "notes": str(status.get("notes") or ""),
        "source_csv_sha256": comment_sha,
    }
    # Compare RAW source text, not derived hashes: a cleaning-rule upgrade must not wipe analyst notes.
    old_raw = {r["comment_id"]:r["comment_text"] for r in db.execute("SELECT comment_id,comment_text FROM comments")}
    changed = [(d["comment_id"],) for d in payload if d["comment_id"] in old_raw and old_raw[d["comment_id"]] != d["comment_text"]]
    # If the attachment inventory changes, prior semantic results may refer to incomplete evidence.
    old_attachment_ids = {(r["comment_id"], r["attachment_id"], r["download_url"]) for r in db.execute("SELECT comment_id,attachment_id,download_url FROM attachments")}
    new_attachment_ids = {(a["comment_id"], a["attachment_id"], a["download_url"]) for a in atts}
    changed_ids = {cid for (cid,) in changed}
    changed_ids.update(k[0] for k in old_attachment_ids.symmetric_difference(new_attachment_ids))
    invalidate_semantic = [(cid,) for cid in sorted(changed_ids)]
    with db:
        # Preserve manual corrections for unchanged records only; changed text invalidates review.
        # Removed comment IDs are pruned after importing the replacement snapshot.
        db.execute("DELETE FROM attachments")
        db.execute("DELETE FROM tags")
        db.execute("DELETE FROM comments")
        cols = FIELDS + ["normalized_sha", "plain_text"]
        db.executemany("INSERT INTO comments (" + ",".join(cols) + ") VALUES (" + ",".join("?" for _ in cols) + ")", [[d[c] for c in cols] for d in payload])
        db.executemany("INSERT INTO attachments (" + ",".join(ATT_FIELDS) + ") VALUES (" + ",".join("?" for _ in ATT_FIELDS) + ")", [[d[c] for c in ATT_FIELDS] for d in atts])
        db.execute("DELETE FROM manual_overrides WHERE comment_id NOT IN (SELECT comment_id FROM comments)")
        db.execute("DELETE FROM analyst_reviews WHERE comment_id NOT IN (SELECT comment_id FROM comments)")
        db.execute("DELETE FROM attachment_text WHERE NOT EXISTS (SELECT 1 FROM attachments a WHERE a.comment_id=attachment_text.comment_id AND a.attachment_id=attachment_text.attachment_id)")
        if changed:
            db.executemany("DELETE FROM manual_overrides WHERE comment_id=?", changed)
            db.executemany("DELETE FROM analyst_reviews WHERE comment_id=?", changed)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='semantic_status'").fetchone():
            # Only preserve semantic labels for identical source text with unchanged attached evidence.
            db.execute("DELETE FROM semantic_tags WHERE comment_id NOT IN (SELECT comment_id FROM comments)")
            db.execute("DELETE FROM semantic_status WHERE comment_id NOT IN (SELECT comment_id FROM comments)")
            if invalidate_semantic:
                db.executemany("DELETE FROM semantic_tags WHERE comment_id=?", invalidate_semantic)
                db.executemany("DELETE FROM semantic_status WHERE comment_id=?", invalidate_semantic)
        db.executemany("INSERT OR REPLACE INTO meta(key,val) VALUES(?,?)", import_meta.items())
        n_tags = _write_derived(db)
        db.execute("INSERT INTO imports(at,row_count,comment_ids,input_sha256,mode,note) VALUES (?,?,?,?,?,?)", (utc_now(), len(rows), len(seen), comment_sha, mode, "Atomic exact-snapshot replacement"))
    return {"records":len(payload), "tag_assignments":n_tags, "attachments":len(atts),
            "attachment_metadata_source": attachment_source, "indexed_count":indexed, "api_total":total,
            "blank_full_text":sum(not normalize(d["plain_text"]) for d in payload)}


ATTACH_REF_RE = re.compile(r"\b(?:attach(?:ed|ment|ments)?|enclosed|uploaded|see\s+file)\b", re.I)


def _int(value):
    try:
        return int(str(value or "0").strip() or 0)
    except ValueError:
        return 0


def attachment_dependent_ids(db):
    """Records whose substance is probably in an attachment, not the body.

    V5 used SQL ``LIKE 'see attached%'`` and missed 'Please see attached comments', bodies that are
    only a document title, etc. Rule: has an attachment AND (blank body, OR body <= 300 chars that
    refers to an attachment, OR body <= 120 chars).
    """
    out = []
    for r in db.execute("""SELECT c.comment_id,c.plain_text,c.attachment_count,
                           (SELECT COUNT(*) FROM attachments a WHERE a.comment_id=c.comment_id) n
                           FROM comments c ORDER BY c.comment_id"""):
        if _int(r["attachment_count"]) <= 0 and not r["n"]:
            continue
        t = (r["plain_text"] or "").strip()
        if not t or len(t) <= 120 or (len(t) <= 300 and ATTACH_REF_RE.search(t)):
            out.append(r["comment_id"])
    return out


def possible_truncation_ids(db):
    """Source-side truncation candidates (Regulations.gov sometimes cuts text at an apostrophe).

    Flags raw text ending in an apostrophe entity, or very short bodies (< 60 chars) with no
    attachment that end mid-word. Triage signal only: verify against the public record.
    """
    out = []
    for r in db.execute("SELECT comment_id,comment_text,plain_text,attachment_count FROM comments ORDER BY comment_id"):
        raw = (r["comment_text"] or "").rstrip()
        t = (r["plain_text"] or "").strip()
        if re.search(r"(?:&#39;|&rsquo;|['’])s?$", raw) or (
                t and len(t) < 60 and _int(r["attachment_count"]) == 0 and t[-1].isalnum() and "@" not in t):
            out.append(r["comment_id"])
    return out


def same_submitter_duplicates(db):
    """Identical normalized text submitted more than once under the same (non-anonymous) name."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in db.execute("SELECT comment_id,first_name,last_name,normalized_sha FROM comments WHERE normalized_sha<>'' ORDER BY comment_id"):
        name = normalize(f"{r['first_name']} {r['last_name']}")
        if not name or "anonymous" in name:
            continue
        groups[(name, r["normalized_sha"])].append(r["comment_id"])
    return [{"size": len(ids), "comment_ids": ids, "extra_records": len(ids) - 1} for ids in groups.values() if len(ids) > 1]


def cluster_map(db):
    return {r["comment_id"]: dict(r) for r in db.execute("SELECT * FROM comment_clusters")}


def cluster_stats(db):
    cm = cluster_map(db)
    sizes = Counter(v["cluster_id"] for v in cm.values())
    multi = {k: v for k, v in sizes.items() if v > 1}
    largest = max(sizes.values()) if sizes else 0
    return {"distinct_texts": len(sizes),
            "form_letter_clusters": len(multi),
            "records_in_form_letter_clusters": sum(multi.values()),
            "largest_cluster_size": largest,
            "largest_cluster_share": round(largest / len(cm), 4) if cm else 0,
            "personalized_form_letters": sum(v["personalized"] for v in cm.values()),
            "unfilled_template_placeholders": sum(v["unfilled_placeholder"] for v in cm.values()),
            "method": f"Greedy {SHINGLE_WORDS}-word-shingle clustering in comment_id order; joins a representative when shared shingles >= {CLUSTER_OVERLAP:.0%} of the smaller and >= {CLUSTER_MIN_SHARE:.0%} of the larger text"}


def metadata(db):
    m = {r["key"]:r["val"] for r in db.execute("SELECT key,val FROM meta")}
    records = db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    unique_with_text = db.execute("SELECT COUNT(*) FROM comments WHERE TRIM(plain_text) <> ''").fetchone()[0]
    dupe_groups = db.execute("SELECT COUNT(*) FROM (SELECT normalized_sha FROM comments WHERE normalized_sha <> '' GROUP BY normalized_sha HAVING COUNT(*)>1)").fetchone()[0]
    grouped_records = db.execute("SELECT COALESCE(SUM(n),0) FROM (SELECT COUNT(*) n FROM comments WHERE normalized_sha <> '' GROUP BY normalized_sha HAVING COUNT(*)>1)").fetchone()[0]
    att_count = db.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
    att_docs = db.execute("SELECT COUNT(*) FROM (SELECT DISTINCT comment_id, COALESCE(NULLIF(attachment_id,''), download_url) FROM attachments)").fetchone()[0]
    with_attachments = db.execute("SELECT COUNT(*) FROM comments WHERE CAST(attachment_count AS INTEGER)>0 OR comment_id IN (SELECT comment_id FROM attachments)").fetchone()[0]
    att_text_ok = db.execute("SELECT COUNT(*) FROM attachment_text WHERE status IN ('ok','no_text')").fetchone()[0]  # no_text = image reviewed, contains no text
    attached_only = len(attachment_dependent_ids(db))
    unclassified = db.execute("SELECT COUNT(*) FROM comments c WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.comment_id=c.comment_id) AND NOT EXISTS (SELECT 1 FROM manual_overrides o WHERE o.comment_id=c.comment_id AND o.decision=1)").fetchone()[0]
    reviews=db.execute("SELECT COUNT(*) FROM analyst_reviews WHERE review_status='Reviewed'").fetchone()[0]
    followups=db.execute("SELECT COUNT(*) FROM analyst_reviews WHERE review_status='Needs follow-up'").fetchone()[0]
    overrides=db.execute("SELECT COUNT(*) FROM manual_overrides").fetchone()[0]
    indexed = int(m["indexed_count"]) if m.get("indexed_count","").isdigit() else None
    cs = cluster_stats(db)
    ssd = same_submitter_duplicates(db)
    return {"records":records,"with_text":unique_with_text,"blank_text":records-unique_with_text,
       "attachment_metadata_rows":att_count,"attachment_documents":att_docs,
       "attachment_documents_with_extracted_text":att_text_ok,
       "comment_records_with_declared_attachments":with_attachments,"attachment_only_placeholders":attached_only,
       "unclassified_keyword_records":unclassified,"exact_duplicate_groups":dupe_groups,
       "records_in_duplicate_groups":grouped_records,"indexed_count":indexed,
       "distinct_texts":cs["distinct_texts"],"form_letter_clusters":cs["form_letter_clusters"],
       "records_in_form_letter_clusters":cs["records_in_form_letter_clusters"],
       "largest_cluster_size":cs["largest_cluster_size"],"personalized_form_letters":cs["personalized_form_letters"],
       "unfilled_template_placeholders":cs["unfilled_template_placeholders"],
       "same_submitter_duplicate_groups":len(ssd),"same_submitter_extra_records":sum(g["extra_records"] for g in ssd),
       "possible_truncation":len(possible_truncation_ids(db)),
       "analyst_reviewed":reviews,"analyst_needs_followup":followups,"analyst_theme_overrides":overrides,
       "api_total_at_index_time":int(m["api_total_at_index_time"]) if m.get("api_total_at_index_time","").isdigit() else None,
       "mode":m.get("mode","empty"),"imported_at_utc":m.get("imported_at_utc"),
       "source_csv_sha256":m.get("source_csv_sha256",""),
       "index_retrieved_at_utc":m.get("index_retrieved_at_utc",""),
       "themes":len(all_themes()),"label_method":"UNVALIDATED deterministic keyword screening (boilerplate-masked)",
       "taxonomy_version":m.get("taxonomy_version", "unknown"),
       "derivation_version":m.get("derivation_version", "unknown"),
       "warning":"Counts are public COMMENT RECORDS, not verified unique people. ~"+str(cs["records_in_form_letter_clusters"])+" records belong to form-letter clusters; see distinct-text counts. Topic assignments require QC. Attachment documents are analyzed only if extracted locally."}


def filtered_ids(db, theme=None, phrase=None, query_mode="any"):
    # In-memory filtering is deliberately transparent for pilot-scale corpora (<20k records).
    # Database retains ALL comments; search returns all matches, not a model-sampled subset.
    theme_valid = {t["id"] for t in all_themes()}
    if theme and theme not in theme_valid:
        raise ValueError("Unknown theme")
    if theme:
        rows = db.execute("""SELECT c.comment_id,c.plain_text,c.title,c.organization,
                        COALESCE(o.decision, CASE WHEN t.comment_id IS NOT NULL THEN 1 ELSE 0 END) active
                        FROM comments c LEFT JOIN tags t ON t.comment_id=c.comment_id AND t.theme_id=?
                        LEFT JOIN manual_overrides o ON o.comment_id=c.comment_id AND o.theme_id=?
                        ORDER BY c.comment_id""", (theme,theme)).fetchall()
        rows = [r for r in rows if r["active"] == 1]
    else:
        rows = db.execute("SELECT comment_id, plain_text, title, organization FROM comments ORDER BY comment_id").fetchall()
    if phrase:
        terms = re.findall(r'"([^"]+)"|(\S+)', phrase)
        words = [normalize(a or b) for a,b in terms if normalize(a or b)]
        if len(words) > 25:
            raise ValueError("Limit query to 25 terms")
        if query_mode not in ("any", "all", "phrase"):
            raise ValueError("Invalid query mode")
        if query_mode == "phrase":
            words = [normalize(phrase.strip().strip('"'))]
        pred = all if query_mode == "all" else any
        def has_term(haystack, term):
            pattern = r"(?<!\w)" + re.escape(term).replace(r"\ ",r"\s+") + r"(?!\w)"
            return bool(re.search(pattern, haystack))
        rows = [r for r in rows if pred(has_term(normalize(" ".join((r["plain_text"] or "", r["title"] or "", r["organization"] or ""))),w) for w in words)]
    return [r["comment_id"] for r in rows]


def list_comments(db, theme=None, phrase=None, query_mode="any", page=1, size=25, include_all=False):
    ids = filtered_ids(db,theme,phrase,query_mode)
    total = len(ids)
    if not include_all:
        size = max(1,min(int(size),100))
        page = max(1,int(page))
        ids = ids[(page-1)*size:page*size]
    if not ids:
        return {"total":total,"page":page,"comments":[]}
    placeholders = ",".join("?" for _ in ids)
    records = {r["comment_id"]:dict(r) for r in db.execute(f"SELECT * FROM comments WHERE comment_id IN ({placeholders})", ids)}
    for record in records.values():
        record.pop("normalized_sha",None)
    return {"total":total,"page":page,"comments":[records[x] for x in ids]}


def _active_theme_ids(db):
    """{theme_id: set(comment_id)} after applying analyst overrides."""
    from collections import defaultdict
    active = defaultdict(set)
    for r in db.execute("SELECT comment_id, theme_id FROM tags"):
        active[r["theme_id"]].add(r["comment_id"])
    for r in db.execute("SELECT comment_id, theme_id, decision FROM manual_overrides"):
        if r["decision"] == 1:
            active[r["theme_id"]].add(r["comment_id"])
        else:
            active[r["theme_id"]].discard(r["comment_id"])
    return active


def theme_summary(db):
    """Per-theme record counts PLUS distinct-text counts (form-letter clusters counted once)."""
    active = _active_theme_ids(db)
    cm = {cid: v["cluster_id"] for cid, v in cluster_map(db).items()}
    att_src = Counter(r["theme_id"] for r in db.execute("SELECT theme_id FROM tags WHERE source='attachment'"))
    rows = []
    for t in all_themes():
        ids = active.get(t["id"], set())
        clusters = Counter(cm.get(c, c) for c in ids)
        top = clusters.most_common(1)[0][1] if clusters else 0
        rows.append({"id": t["id"], "name": t["name"], "count": len(ids),
                     "distinct_texts": len(clusters),
                     "largest_cluster_records": top,
                     "largest_cluster_share": round(top / len(ids), 3) if ids else 0,
                     "from_attachments": att_src.get(t["id"], 0),
                     "description": t["description"]})
    return sorted(rows, key=lambda x: (-x["count"], x["name"]))


def theme_details(db, cid):
    auto={r["theme_id"]:(r["evidence"],r["keyword"],r["source"]) for r in db.execute("SELECT theme_id,evidence,keyword,source FROM tags WHERE comment_id=?",(cid,))}
    overrides={r["theme_id"]:r["decision"] for r in db.execute("SELECT theme_id,decision FROM manual_overrides WHERE comment_id=?",(cid,))}
    return [{"id":t["id"],"name":t["name"],"active":bool(overrides.get(t["id"], t["id"] in auto)),
             "method":"manual" if t["id"] in overrides else "keyword screening",
             "evidence":auto.get(t["id"],("","",""))[0],"keyword":auto.get(t["id"],("","",""))[1],
             "source":auto.get(t["id"],("","",""))[2]}
            for t in all_themes()]


def save_override(db,cid,theme_id,decision):
    if not db.execute("SELECT 1 FROM comments WHERE comment_id=?",(cid,)).fetchone():
        raise ValueError("Unknown comment")
    if theme_id not in {x["id"] for x in all_themes()}:
        raise ValueError("Unknown theme")
    if decision not in (0,1):
        raise ValueError("decision must be 0 or 1")
    with db:
        db.execute("INSERT OR REPLACE INTO manual_overrides VALUES (?,?,?)",(cid,theme_id,decision))
    return {"comment_id":cid,"theme_id":theme_id,"decision":decision}


def response_review(db, draft):
    if not isinstance(draft,str) or len(draft.strip())<25:
        raise ValueError("Provide at least 25 characters of draft response text")
    tax = taxonomy()
    summary = {t["id"]:t for t in theme_summary(db)}
    output=[]
    for t in tax["themes"]:
        s=summary[t["id"]]
        if not s["count"]: continue
        evidence=rule_match(draft,t["keywords"],(),t.get("keywords_case_sensitive",[]))
        examples=[x["comment_id"] for x in evidence_samples(db, t["id"], count=3)]
        # No claim of semantic coverage. Reviewer manually decides whether response substantively addresses each item.
        output.append({"theme_id":t["id"],"theme":t["name"],"comment_records":s["count"],
                       "distinct_texts":s["distinct_texts"],
                       "screening":"Keyword signal in draft" if evidence else "No keyword signal in draft",
                       "draft_match":bool(evidence),"draft_excerpt":evidence or "",
                       "example_comment_ids":examples,
                       "analyst_status":"Needs human assessment"})
    return {"rows":sorted(output,key=lambda r:(r["draft_match"],-r["distinct_texts"],-r["comment_records"])),
            "limitations":"Keyword overlap is only a triage signal, NOT evidence that a draft substantively addresses a comment or that a topic is omitted. Distinct texts count each form-letter cluster once. Unclassified themes and unextracted attachments may contain missed concerns."}



def save_analyst_review(db, cid, review_status, notes):
    allowed={'Not reviewed','Reviewed','Needs follow-up'}
    if review_status not in allowed:raise ValueError('Invalid review status')
    if not isinstance(notes,str) or len(notes)>15000:raise ValueError('Review notes must be plain text (max 15000 characters)')
    if not db.execute('SELECT 1 FROM comments WHERE comment_id=?',(cid,)).fetchone():raise ValueError('Unknown comment')
    with db:
        db.execute('INSERT OR REPLACE INTO analyst_reviews VALUES (?,?,?,?)',(cid,review_status,notes,utc_now()))
    return {'comment_id':cid,'review_status':review_status,'updated_utc':utc_now()}


def review_queue(db, limit=100):
    """Prioritized analyst triage list (explicit rules, not LLM judgments)."""
    att_dep = set(attachment_dependent_ids(db))
    trunc = set(possible_truncation_ids(db))
    cm = cluster_map(db)
    reviewed = {r["comment_id"] for r in db.execute("SELECT comment_id FROM analyst_reviews WHERE review_status='Reviewed'")}
    extracted = {r["comment_id"] for r in db.execute("SELECT DISTINCT comment_id FROM attachment_text WHERE status IN ('ok','no_text')")}
    rows = db.execute("""SELECT c.comment_id,c.title,c.comment_url,c.plain_text,c.attachment_count,c.organization,
      COUNT(t.theme_id) screened_themes FROM comments c
      LEFT JOIN tags t ON c.comment_id=t.comment_id
      GROUP BY c.comment_id ORDER BY c.comment_id""").fetchall()
    out = []
    for r in rows:
        if r["comment_id"] in reviewed:
            continue
        reasons, score = [], 0
        cl = cm.get(r["comment_id"], {})
        if r["comment_id"] in att_dep and r["comment_id"] not in extracted:
            reasons.append("substance likely in unextracted attachment"); score += 4
        if r["organization"]:
            reasons.append("organizational submitter"); score += 2
        if r["comment_id"] in trunc:
            reasons.append("possible source truncation"); score += 2
        if r["screened_themes"] == 0:
            reasons.append("no keyword theme"); score += 2
        if cl.get("cluster_size", 1) == 1 and len(r["plain_text"] or "") >= 1500:
            reasons.append("long unique comment"); score += 1
        if cl.get("personalized"):
            reasons.append("personalized form letter"); score += 1
        if not reasons:
            continue
        out.append({"comment_id":r["comment_id"],"title":r["title"],"comment_url":r["comment_url"],
                    "screened_theme_count":r["screened_themes"],"attachment_count":r["attachment_count"],
                    "priority":score,"reasons":"; ".join(reasons),"preview":(r["plain_text"] or "")[:320]})
    out.sort(key=lambda x: (-x["priority"], x["screened_theme_count"], x["comment_id"]))
    return out[:max(1, min(int(limit), 2000))]


def date_summary(db):
    rows=db.execute("""SELECT SUBSTR(posted_date,1,10) day,COUNT(*) n FROM comments
     WHERE TRIM(posted_date)<>'' GROUP BY day ORDER BY day""").fetchall()
    return [{"day":r["day"],"count":r["n"]} for r in rows]


def template_groups(db):
    """Form-letter clusters (near-duplicate text), largest first. Exploratory: not proof of coordination."""
    cm = cluster_map(db)
    members = {}
    for cid, v in sorted(cm.items()):
        members.setdefault(v["cluster_id"], []).append(v)
    result = []
    for rep, vs in members.items():
        if len(vs) < 2:
            continue
        text = db.execute("SELECT plain_text FROM comments WHERE comment_id=?", (rep,)).fetchone()
        result.append({"cluster_id": rep, "size": len(vs),
                       "example_comment_ids": [v["comment_id"] for v in vs[:5]],
                       "personalized": sum(v["personalized"] for v in vs),
                       "unfilled_placeholders": sum(v["unfilled_placeholder"] for v in vs),
                       "shared_opening": normalize(text[0] if text else "")[:220],
                       "method": "near-duplicate 5-word shingle clustering"})
    return sorted(result, key=lambda x: (-x["size"], x["cluster_id"]))


def analysis_qc(db):
    m=metadata(db)
    idx=db.execute("SELECT val FROM meta WHERE key='index_retrieved_at_utc'").fetchone()
    grps=template_groups(db)
    all_index=m.get("indexed_count")
    ssd=same_submitter_duplicates(db)
    return {"records":m["records"], "indexed_count":all_index,
            "indexed_missing":max(0,all_index-m["records"]) if all_index is not None else None,
            "index_snapshot_time":idx[0] if idx else None,
            "daily_postings":date_summary(db),
            "shared_opening_group_count":len(grps),
            "shared_opening_records":sum(g["size"] for g in grps),
            "distinct_texts":m["distinct_texts"],
            "largest_cluster_size":m["largest_cluster_size"],
            "personalized_form_letters":m["personalized_form_letters"],
            "unfilled_template_placeholders":m["unfilled_template_placeholders"],
            "same_submitter_duplicate_groups":len(ssd),
            "same_submitter_extra_records":sum(g["extra_records"] for g in ssd),
            "attachment_documents":m["attachment_documents"],
            "attachment_metadata_rows":m["attachment_metadata_rows"],
            "attachment_dependent_records":m["attachment_only_placeholders"],
            "attachment_documents_with_extracted_text":m["attachment_documents_with_extracted_text"],
            "possible_truncation":m["possible_truncation"],
            "analyst_reviewed":m["analyst_reviewed"],"analyst_needs_followup":m["analyst_needs_followup"],
            "shared_opening_groups":grps[:20],
            "review_queue":review_queue(db,30),
            "method_notes":["Public submissions received is not identical to public comments posted.",
                "Form-letter clusters are near-duplicate text groups; they do not establish coordination, unique people, or redundancy for response purposes.",
                "Attachment file renditions (e.g. PDF + DOCX of one document) are counted once as attachment documents.",
                "All thematic counts are exploratory keyword screening with template-boilerplate masking. Human validation remains pending."]}


def evidence_samples(db, theme_id, count=5):
    """One example per distinct text, largest clusters first, so examples cover the main variants."""
    if theme_id not in {x['id'] for x in all_themes()}:
        raise ValueError('Unknown theme')
    ids=filtered_ids(db,theme=theme_id)
    if not ids:return []
    cm=cluster_map(db)
    by_cluster={}
    for cid in ids:
        by_cluster.setdefault(cm.get(cid,{}).get("cluster_id",cid),[]).append(cid)
    ordered=sorted(by_cluster.items(),key=lambda kv:(-len(kv[1]),kv[1][0]))
    output=[]
    for cluster_id,members in ordered[:count]:
        cid=members[0]
        r=db.execute('SELECT comment_id,comment_url,title,plain_text,attachment_count FROM comments WHERE comment_id=?',(cid,)).fetchone()
        tag=db.execute('SELECT evidence,keyword FROM tags WHERE comment_id=? AND theme_id=?',(cid,theme_id)).fetchone()
        output.append({'comment_id':cid,'source_url':r['comment_url'],'title':r['title'],
                       'matched_excerpt':tag[0] if tag else 'Analyst override; no keyword excerpt',
                       'matched_keyword':tag[1] if tag else '',
                       'records_with_this_text_in_theme':len(members),
                       'text_preview':r['plain_text'][:420],'attachment_count':r['attachment_count']})
    return output


def validation_sample(db, per_stratum=8, seed=20261019):
    """Stratified sample for human coding: per theme, screen-positive and screen-negative records.

    Code human_label as 1 (theme present) / 0 (absent). scripts/score_validation.py turns the coded
    file into precision, stratum-weighted recall and F1 with 95% intervals.
    """
    import random
    rng = random.Random(seed)
    active = _active_theme_ids(db)
    all_ids = [r[0] for r in db.execute("SELECT comment_id FROM comments ORDER BY comment_id")]
    texts = {r["comment_id"]: r for r in db.execute("SELECT comment_id,comment_url,plain_text FROM comments")}
    tags = {(r["comment_id"], r["theme_id"]): r["evidence"] for r in db.execute("SELECT comment_id,theme_id,evidence FROM tags")}
    rows = []
    for t in all_themes():
        pos = sorted(active.get(t["id"], set()))
        neg = [c for c in all_ids if c not in active.get(t["id"], set())]
        for stratum, pool in (("screen_positive", pos), ("screen_negative", neg)):
            for cid in sorted(rng.sample(pool, min(per_stratum, len(pool)))):
                rows.append({"sample_id": f"{t['id']}|{stratum}|{cid}", "theme_id": t["id"], "theme": t["name"],
                             "theme_definition": t["description"], "stratum": stratum,
                             "stratum_population": len(pool), "comment_id": cid,
                             "comment_url": texts[cid]["comment_url"], "screen_evidence": tags.get((cid, t["id"]), ""),
                             "comment_text": (texts[cid]["plain_text"] or "")[:3000],
                             "human_label": "", "coder": "", "notes": ""})
    return rows


def management_html(db):
    """Print-friendly frozen snapshot with explicit analytical limitations."""
    from html import escape
    m=metadata(db); qc=analysis_qc(db); themes=theme_summary(db)
    def e(val):return escape(str(val if val is not None else 'Not supplied'),quote=True)
    rows=''.join(f'<tr><td>{e(x["name"])}</td><td>{x["count"]}</td><td>{round(x["count"]/m["records"]*100,1) if m["records"] else 0}%</td><td>{x["distinct_texts"]}</td><td>{round(100*x["largest_cluster_share"])}%</td></tr>' for x in themes)
    dates=''.join(f'<tr><td>{e(x["day"])}</td><td>{x["count"]}</td></tr>' for x in qc['daily_postings'])
    groups=''.join(f'<tr><td>{g["size"]}</td><td>{g["personalized"]}</td><td>{e(", ".join(g["example_comment_ids"][:3]))}</td><td>{e(g["shared_opening"][:160])}…</td></tr>' for g in qc['shared_opening_groups'][:10])
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>NHIS Comment Corpus — QC briefing</title><style>
body{{font-family:Arial,sans-serif;margin:32px auto;padding:0 22px;max-width:980px;color:#20302c;line-height:1.5}}
h1{{font-size:26px}}h2{{margin-top:28px;color:#0e665b;font-size:18px}}table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid #dae3dc;padding:8px;text-align:left;font-size:12px}}th{{background:#e8f0eb}}
.warning{{background:#fff3dc;border:1px solid #d6b875;padding:14px}}.muted{{color:#596a63}}@media print{{body{{margin:0}}}}
</style><h1>NHIS Public Comment Intelligence — corpus QC briefing</h1>
<p class="muted">Docket CDC-2026-1387 · Offline snapshot · Generated {e(utc_now())} · Taxonomy {e(m['taxonomy_version'])} · Derivation {e(m['derivation_version'])}</p>
<div class="warning"><b>Internal preliminary analytical product — not a validated thematic report.</b>
Keyword flags are exploratory and have not been validated against human coding; most records belong to form-letter clusters; attachment contents are included only where extracted locally; total submissions received have not been reconciled with publicly posted comments.</div>
<h2>Source integrity</h2><table><tr><th>Measure</th><th>Value</th></tr>
<tr><td>Public comment records loaded</td><td>{m['records']}</td></tr>
<tr><td>Public API index at snapshot</td><td>{e(m['indexed_count'])}</td></tr>
<tr><td>Missing from that index</td><td>{e(qc['indexed_missing'])}</td></tr>
<tr><td>API index timestamp (UTC)</td><td>{e(m['index_retrieved_at_utc'])}</td></tr>
<tr><td>Distinct texts (form-letter clusters counted once)</td><td>{m['distinct_texts']}</td></tr>
<tr><td>Records in form-letter clusters / clusters</td><td>{m['records_in_form_letter_clusters']} / {m['form_letter_clusters']}</td></tr>
<tr><td>Largest single cluster (records)</td><td>{m['largest_cluster_size']}</td></tr>
<tr><td>Personalized form letters (≥{PERSONALIZED_MIN_WORDS} new words)</td><td>{m['personalized_form_letters']}</td></tr>
<tr><td>Form letters with unfilled template placeholder</td><td>{m['unfilled_template_placeholders']}</td></tr>
<tr><td>Same-name identical resubmissions (extra records)</td><td>{m['same_submitter_extra_records']}</td></tr>
<tr><td>Attachment documents (file renditions)</td><td>{m['attachment_documents']} ({m['attachment_metadata_rows']})</td></tr>
<tr><td>Attachment documents with extracted text</td><td>{m['attachment_documents_with_extracted_text']}</td></tr>
<tr><td>Records whose substance is likely in an attachment</td><td>{m['attachment_only_placeholders']}</td></tr>
<tr><td>Possible source truncation (verify at source)</td><td>{m['possible_truncation']}</td></tr>
<tr><td>Exact duplicate text groups</td><td>{m['exact_duplicate_groups']}</td></tr>
<tr><td>Corpus SHA-256</td><td><small>{e(m['source_csv_sha256'])}</small></td></tr></table>
<h2>Screening frequencies (not validated findings)</h2>
<p>Records = comment records with rule hits (template boilerplate masked) and analyst overrides. Distinct texts = number of different texts among them, with each form-letter cluster counted once. Multi-label categories overlap and cannot be summed. Counts do not indicate unique individuals, sentiment, agency response needs or statistically estimated prevalence.</p>
<table><tr><th>Provisional theme</th><th>Records</th><th>% of loaded records</th><th>Distinct texts</th><th>Share from largest cluster</th></tr>{rows}</table>
<h2>Largest form-letter clusters</h2><table><tr><th>Records</th><th>Personalized</th><th>Example IDs</th><th>Opening</th></tr>{groups}</table>
<h2>Posting dates in imported snapshot</h2><table><tr><th>Date</th><th>Records</th></tr>{dates}</table>
<h2>Required before management analytical findings</h2><p>Reconcile the public index to a fresh inventory and distinguish it from received submissions; extract attachment text (scripts/extract_attachments.py) or flag it as unavailable; human-code the validation sample (validation_sample export) and score it (scripts/score_validation.py); substantively review draft responses.</p>
<p class="muted">This report is a local snapshot; print or Save as PDF from your browser.</p></html>"""


def safe_csv_cell(value):
    val=str(value if value is not None else "")
    # Prevent formula injection when opening CSV in Excel. Preserve original in database/UI.
    if val.lstrip().startswith(("=","+","-","@")):
        return "'" + val
    return val


def to_csv(headers,rows):
    stream=io.StringIO(newline="")
    writer=csv.writer(stream)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv_cell(row.get(k,"")) for k in headers])
    return "\ufeff" + stream.getvalue()


def export_report(db, kind, draft="", theme=None, phrase=None, query_mode="any"):
    if kind == "corpus_qc":
        headings=["check","value","interpretation"]
        m=metadata(db)
        checks=[("loaded_comment_records",m["records"],"Unique comment IDs in the imported CSV"),
                ("api_index_records",m["indexed_count"],"Index snapshot; not independently reconciled with website"),
                ("api_reported_total_at_index_time",m["api_total_at_index_time"],"Historical API total"),
                ("records_pending_from_index",max(0,m["indexed_count"]-m["records"]) if m["indexed_count"] is not None else "unknown","Indexed IDs not yet present in imported snapshot"),
                ("distinct_texts",m["distinct_texts"],"Records after collapsing each near-duplicate form-letter cluster to one"),
                ("form_letter_clusters",m["form_letter_clusters"],"Clusters with 2+ near-duplicate records"),
                ("records_in_form_letter_clusters",m["records_in_form_letter_clusters"],"Records sharing near-identical text with at least one other record"),
                ("largest_cluster_size",m["largest_cluster_size"],"Records in the single largest form-letter cluster"),
                ("personalized_form_letters",m["personalized_form_letters"],f"Cluster members adding >= {PERSONALIZED_MIN_WORDS} new 5-word sequences"),
                ("unfilled_template_placeholders",m["unfilled_template_placeholders"],"Bracketed template instructions left unedited"),
                ("same_submitter_extra_records",m["same_submitter_extra_records"],"Identical text resubmitted under the same name (extra copies)"),
                ("comment_records_with_declared_attachments",m["comment_records_with_declared_attachments"],"Records listing one or more attachments"),
                ("attachment_documents",m["attachment_documents"],"Distinct attached documents"),
                ("attachment_metadata_rows",m["attachment_metadata_rows"],"File renditions (one document may have PDF + DOCX)"),
                ("attachment_documents_with_extracted_text",m["attachment_documents_with_extracted_text"],"Attachments whose text is included in screening"),
                ("attachment_only_placeholders",m["attachment_only_placeholders"],"Body is blank/very short/refers to attachment; substance likely in attachment"),
                ("possible_truncation",m["possible_truncation"],"Body may be cut off at the source; verify on Regulations.gov"),
                ("unclassified_keyword_records",m["unclassified_keyword_records"],"No keyword themes; not evidence of no substantive themes"),
                ("exact_duplicate_groups",m["exact_duplicate_groups"],"Exact normalized body matches only"),
                ("last_import_utc",m["imported_at_utc"],"Dashboard local import timestamp"),
                ("source_csv_sha256",m["source_csv_sha256"],"SHA-256 of imported source CSV; enables provenance checks"),
                ("classification_method",m["label_method"],"Screening only, not management-grade topic prevalence"),
                ("analyst_reviewed",m["analyst_reviewed"],"Manually marked reviewed; not a validated classification accuracy metric"),
                ("analyst_followup",m["analyst_needs_followup"],"Marked by an analyst as requiring follow-up"),
                ("taxonomy_version",m["taxonomy_version"],"Screening taxonomy version"),
                ("derivation_version",m["derivation_version"],"Text-cleaning / tagging / clustering code version"),
                ("shared_opening_candidate_groups",len(template_groups(db)),"Form-letter clusters (near-duplicate method in V6)")]
        vals=[{"check":a,"value":b,"interpretation":c} for a,b,c in checks]
    elif kind == "theme_counts":
        headings=["theme_id","theme","comment_records","percent_of_records","distinct_texts","largest_cluster_share","from_attachments","method"]
        n=metadata(db)["records"]
        vals=[{"theme_id":r["id"],"theme":r["name"],"comment_records":r["count"],
               "percent_of_records":round(100*r["count"]/n,2) if n else 0,
               "distinct_texts":r["distinct_texts"],"largest_cluster_share":r["largest_cluster_share"],
               "from_attachments":r["from_attachments"],
               "method":"Unvalidated keyword screen (boilerplate-masked) + analyst overrides"} for r in theme_summary(db)]
    elif kind=="all_comments":
        headings=FIELDS
        vals=[dict(row) for row in db.execute("SELECT "+",".join(FIELDS)+" FROM comments ORDER BY comment_id")]
    elif kind=="attachment_gaps":
        headings=["comment_id","source_url","attachment_count_declared","attachment_metadata_rows","attachment_dependent","comment_text_preview","needs_attachment_text"]
        dep=set(attachment_dependent_ids(db))
        done={(r[0],r[1]) for r in db.execute("SELECT comment_id, attachment_id FROM attachment_text WHERE status IN ('ok','no_text')")}
        vals=[]
        for r in db.execute("""SELECT c.comment_id,c.comment_url,c.attachment_count,c.plain_text,
                             (SELECT COUNT(*) FROM attachments a WHERE a.comment_id=c.comment_id) n
                             FROM comments c WHERE CAST(c.attachment_count AS INTEGER)>0
                             OR EXISTS(SELECT 1 FROM attachments a WHERE a.comment_id=c.comment_id)
                             ORDER BY c.comment_id"""):
            vals.append({"comment_id":r["comment_id"],"source_url":r["comment_url"],
                         "attachment_count_declared":r["attachment_count"],
                         "attachment_metadata_rows":r["n"],
                         "attachment_dependent":"YES" if r["comment_id"] in dep else "no",
                         "comment_text_preview":r["plain_text"][:250],
                         "needs_attachment_text":("no — all listed documents extracted" if all(
                             (r['comment_id'], a[0]) in done for a in db.execute(
                                 'SELECT DISTINCT attachment_id FROM attachments WHERE comment_id=?', (r['comment_id'],)))
                             and r['n'] > 0 else "YES — one or more documents not extracted")})
    elif kind=="attachments":
        headings=ATT_FIELDS
        vals=[dict(row) for row in db.execute("SELECT "+",".join(ATT_FIELDS)+" FROM attachments ORDER BY comment_id")]
    elif kind=="attachment_text_status":
        headings=["comment_id","attachment_id","format","method","status","chars","file_sha256","extracted_utc"]
        vals=[dict(r) for r in db.execute("SELECT comment_id,attachment_id,format,method,status,chars,file_sha256,extracted_utc FROM attachment_text ORDER BY comment_id,attachment_id")]
    elif kind=="analyst_reviews":
        headings=["comment_id","review_status","notes","updated_utc"]
        vals=[dict(r) for r in db.execute("SELECT * FROM analyst_reviews ORDER BY comment_id")]
    elif kind=="review_queue":
        headings=["comment_id","title","comment_url","priority","reasons","screened_theme_count","attachment_count","preview"]
        vals=review_queue(db,2000)
    elif kind=="template_groups":
        headings=["cluster_id","size","personalized","unfilled_placeholders","shared_opening","example_comment_ids","method"]
        vals=[{**g,"example_comment_ids":" | ".join(g["example_comment_ids"])} for g in template_groups(db)]
    elif kind=="clusters":
        headings=["comment_id","cluster_id","cluster_size","overlap","novel_words","personalized","unfilled_placeholder"]
        vals=[dict(r) for r in db.execute("SELECT * FROM comment_clusters ORDER BY cluster_size DESC, cluster_id, comment_id")]
    elif kind=="same_submitter_duplicates":
        headings=["size","extra_records","comment_ids"]
        vals=[{**g,"comment_ids":" | ".join(g["comment_ids"])} for g in same_submitter_duplicates(db)]
    elif kind=="evidence_samples":
        headings=["theme","comment_id","source_url","title","matched_keyword","matched_excerpt","records_with_this_text_in_theme","text_preview","attachment_count"]
        vals=[]
        for t in all_themes():
            vals.extend([{"theme":t["name"],**r} for r in evidence_samples(db,t["id"],count=5)])
    elif kind=="validation_sample":
        headings=["sample_id","theme_id","theme","theme_definition","stratum","stratum_population","comment_id","comment_url","screen_evidence","comment_text","human_label","coder","notes"]
        vals=validation_sample(db)
    elif kind=="daily_postings":
        headings=["day","count"]
        vals=date_summary(db)
    elif kind=="theme_assignments":
        headings=["comment_id","theme_id","theme","method","keyword","source","cluster_id","evidence"]
        cm=cluster_map(db)
        vals=[]
        for r in db.execute("SELECT comment_id FROM comments ORDER BY comment_id"):
            for t in theme_details(db,r["comment_id"]):
                if t["active"]:
                    vals.append({"comment_id":r["comment_id"],"theme_id":t["id"],"theme":t["name"],"method":t["method"],
                                 "keyword":t["keyword"],"source":t["source"],
                                 "cluster_id":cm.get(r["comment_id"],{}).get("cluster_id",""),"evidence":t["evidence"]})
    elif kind=="query_matches":
        headings=FIELDS
        vals=list_comments(db,theme,phrase,query_mode,include_all=True)["comments"]
    elif kind=="response_gap_review":
        headings=["theme_id","theme","comment_records","distinct_texts","screening","draft_excerpt","example_comment_ids","analyst_status"]
        results=response_review(db,draft)
        vals=[{**r,"example_comment_ids":" | ".join(r["example_comment_ids"])} for r in results["rows"]]
    else:
        raise ValueError("Unknown export")
    return to_csv(headings,vals)
