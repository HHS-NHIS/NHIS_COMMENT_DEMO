#!/usr/bin/env python3
"""NHIS public comment pilot; paid OpenAI calls are explicit and opt-in."""
import argparse
import base64
import binascii
import hmac
import csv
import io
import sqlite3
import time
import threading
import logging
import json
import mimetypes
import os
import shutil
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from local_analysis import local_models, answer as local_answer, compare_theme
import management_addon as management  # additive, read-only reporting; no existing route overrides
import v107_overlay as feedback  # V10.7 immutable feedback index
from core import (connect as core_connect, import_data, metadata, theme_summary, all_themes, list_comments,
                  theme_details, save_override, response_review, export_report, DB_PATH,
                  source_status, sync_from_folder, analysis_qc, management_html, save_analyst_review,
                  rebuild_derived, ensure_derived_current, cluster_subjects)

ASSETS=Path(__file__).resolve().parent
MAX_BODY_BYTES=(80*1024 if os.getenv('NHIS_DEPLOYMENT_MODE','local').lower()=='hosted' else 75*1024*1024)
HOSTED = os.getenv('NHIS_DEPLOYMENT_MODE','local').strip().lower() == 'hosted'
PUBLIC_DEMO = HOSTED and os.getenv('NHIS_PUBLIC_DEMO','0').strip() == '1'
READ_ONLY = HOSTED or os.getenv('NHIS_READ_ONLY','0') == '1'
HOSTED_ALLOWED_POSTS = {'/api/local/query'}  # Original hosted evidence-only allowlist; unchanged.
# Private local read-only preview allows only deterministic draft keyword checks/CSV.
# These functions read the SQLite snapshot and NEVER save draft text or write data.
PRIVATE_PREVIEW = not HOSTED and READ_ONLY and os.getenv('NHIS_MANAGEMENT_PREVIEW','0') == '1'
READ_ONLY_ALLOWED_POSTS = HOSTED_ALLOWED_POSTS | ({'/api/review','/api/export_review'} if PRIVATE_PREVIEW else set())
HOSTED_ORIGIN=os.getenv('NHIS_PUBLIC_ORIGIN','').strip().rstrip('/').lower()
_LOGIN_LOCK=threading.Lock()
_LOGIN_FAILURES={}
# Behind Railway's proxy every TCP peer is the proxy, so throttling on the socket address would let one
# person's failed logins lock out ALL users. Use the address the proxy forwards. The RIGHTMOST
# X-Forwarded-For entry is the one added by the trusted proxy (a visitor cannot forge it).
TRUST_PROXY = HOSTED and os.getenv('NHIS_TRUST_PROXY','1')=='1'
LOGIN_MAX_FAILURES=15
LOGIN_WINDOW_SECONDS=60

def connect():
    if not READ_ONLY:
        return core_connect()
    # Immutable read-only snapshot: SQLite takes no locks and creates no -wal/-shm files, so the shared
    # demo cannot stall on file locking (seen on Windows with a WAL-mode file) or modify the snapshot.
    db=sqlite3.connect(DB_PATH.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def hosted_snapshot_problem():
    """An immutable connection ignores any -wal file, so a WAL-mode snapshot could silently hide data."""
    if not DB_PATH.is_file():
        return f'Database not found: {DB_PATH}'
    with open(DB_PATH,'rb') as fh:
        header=fh.read(20)
    if header[:16]!=b'SQLite format 3\x00':
        return 'Database file is not a SQLite 3 database'
    if header[18]==2 or header[19]==2:
        return ('Database is in WAL journal mode (it was opened locally after packaging). '
                'Run: python scripts\\prepare_release.py  before deploying.')
    wal=DB_PATH.with_name(DB_PATH.name+'-wal')
    if wal.exists() and wal.stat().st_size>0:
        return 'Unflushed -wal file next to the database. Run: python scripts\\prepare_release.py'
    return None

def semantic_module():
    from pathlib import Path
    scripts_dir=str(ASSETS.parent/'scripts')
    if scripts_dir not in sys.path:sys.path.insert(0,scripts_dir)
    import semantic_classify
    return semantic_classify

def feedback_options(q, management_view=False):
    selected=q.get('theme','')
    extra_topic=selected[len('v108__'):] if selected.startswith('v108__') else ''
    return dict(mode=q.get('form_mode','all'), section=q.get('section','') if management_view else '',
        legacy_theme='' if extra_topic else selected, topic=extra_topic or q.get('v107_topic',''),
        tier=q.get('v107_tier','any'), subcategory=q.get('v107_content',''),
        query=q.get('q',''), match=q.get('match','any'),
        questionnaire=q.get('questionnaire',''))

def feedback_requested(q):
    return any(q.get(k) for k in ('form_mode','v107_topic','v107_tier','v107_content'))

def sem_csv(db,kind):
    sql={
      'assignments': '''SELECT t.comment_id,t.theme_id,t.model,t.evidence,s.status,s.needs_review,s.note,c.comment_url
            FROM semantic_tags t JOIN semantic_status s ON t.comment_id=s.comment_id
            JOIN comments c ON c.comment_id=t.comment_id ORDER BY t.theme_id,t.comment_id''',
      'review_queue': '''SELECT s.comment_id,s.status,s.needs_review,s.note,c.comment_url,substr(c.plain_text,1,1000) AS comment_excerpt
            FROM semantic_status s JOIN comments c ON c.comment_id=s.comment_id
            WHERE s.needs_review=1 OR s.status!='ok' OR EXISTS
            (SELECT 1 FROM semantic_tags t WHERE t.comment_id=s.comment_id
             AND (length(trim(t.evidence))-length(replace(trim(t.evidence),' ',''))<3))
            ORDER BY s.status,s.comment_id''',
      'counts': '''SELECT t.theme_id,COUNT(*) AS provisional_matched_records,
                 COUNT(DISTINCT cl.cluster_id) AS approximate_template_groups,
                 SUM(CASE WHEN s.needs_review=1 THEN 1 ELSE 0 END) AS requiring_review,
                 'UNVALIDATED - FORM LETTER INCONSISTENCY - NOT A PREVALENCE ESTIMATE' AS warning
            FROM semantic_tags t JOIN semantic_status s ON s.comment_id=t.comment_id
            LEFT JOIN comment_clusters cl ON cl.comment_id=t.comment_id
            GROUP BY t.theme_id ORDER BY provisional_matched_records DESC''',
    }.get(kind)
    if not sql:raise ValueError('Unknown semantic report')
    rows=db.execute(sql)
    out=io.StringIO(newline='');w=csv.writer(out)
    w.writerow([c[0] for c in rows.description]);w.writerows(tuple(r) for r in rows)
    return out.getvalue().encode('utf-8-sig')



class Handler(BaseHTTPRequestHandler):
    server_version="NHISCommentQC/0.7-openai"
    def log_message(self, fmt, *args):
        if not self.path.startswith('/api/meta'):
            super().log_message(fmt, *args)

    def _client_key(self):
        if TRUST_PROXY:
            parts=[p.strip() for p in self.headers.get('X-Forwarded-For','').split(',') if p.strip()]
            if parts:return parts[-1]
            real=self.headers.get('X-Real-IP','').strip()
            if real:return real
        return self.client_address[0]

    def _authorized(self):
        if not HOSTED or PUBLIC_DEMO:return True
        peer=self._client_key()
        now=time.monotonic()
        with _LOGIN_LOCK:
            failures=[t for t in _LOGIN_FAILURES.get(peer,[]) if now-t<LOGIN_WINDOW_SECONDS]
            _LOGIN_FAILURES[peer]=failures
            if len(_LOGIN_FAILURES)>5000:  # bound memory
                for k in [k for k,v in _LOGIN_FAILURES.items() if not v][:4000]:_LOGIN_FAILURES.pop(k,None)
            if len(failures)>=LOGIN_MAX_FAILURES:
                self._response({'error':'Too many login attempts. Try again shortly.'},429)
                return False
        header=self.headers.get('Authorization','')
        try:
            if not header.startswith('Basic '):raise ValueError('missing Basic header')
            raw=base64.b64decode(header[6:].strip(),validate=True).decode('utf-8')
            supplied_user,supplied_password=raw.split(':',1)
            username=os.environ['DEMO_USER'];password=os.environ['DEMO_PASSWORD']
            correct=(hmac.compare_digest(supplied_user.encode('utf-8'),username.encode('utf-8'))
                  & hmac.compare_digest(supplied_password.encode('utf-8'),password.encode('utf-8')))
        except (ValueError,UnicodeDecodeError,binascii.Error,KeyError):correct=False
        if not correct:
            with _LOGIN_LOCK:
                _LOGIN_FAILURES.setdefault(peer,[]).append(now)
            self._auth_challenge()
        else:
            with _LOGIN_LOCK:_LOGIN_FAILURES.pop(peer,None)
        return bool(correct)

    def _auth_challenge(self):
        self._response({'error':'Authentication required'},401,
            extra={'WWW-Authenticate':'Basic realm="NHIS Comment Demo", charset="UTF-8"'})

    def _response(self, content, code=200, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(content,(dict,list)):
            content=json.dumps(content,ensure_ascii=False).encode('utf-8')
        elif isinstance(content,str):
            content=content.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',ctype)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control','no-store')
        if HOSTED: self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
        self.send_header('Content-Length',str(len(content)))
        for key,value in (extra or {}).items():self.send_header(key,value)
        self.end_headers()
        self.wfile.write(content)

    def _json(self,data,code=200): self._response(data,code)

    def _body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<1 or size>MAX_BODY_BYTES: raise ValueError('Missing or oversized request')
        data=self.rfile.read(size)
        return json.loads(data.decode('utf-8'))

    def _query(self): return {k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items()}

    def _check_local_origin(self):
        origin=self.headers.get('Origin','').strip().lower().rstrip('/')
        host=self.headers.get('Host','').strip().lower()
        if self.headers.get('Sec-Fetch-Site','')=='cross-site':
            raise ValueError('Cross-site requests are not permitted')
        if HOSTED:
            if origin:
                # The public origin must be explicitly configured in production.
                allowed=HOSTED_ORIGIN or ('https://'+host)
                if origin != allowed:
                    raise ValueError('Cross-origin writes are not permitted')
            # Origin-less scripted GET-compatible local evidence requests allowed with authentication.
        else:
            if host.split(':')[0] not in ('127.0.0.1','localhost'):
                raise ValueError('Dashboard accepts loopback requests only')
            if origin and origin not in ('http://'+host,'https://'+host):
                raise ValueError('Cross-origin writes are not permitted')

    def do_HEAD(self):
        if urlsplit(self.path).path!='/healthz':
            self.send_response(404);self.end_headers();return
        self.send_response(200)
        self.send_header('Content-Length','0');self.end_headers()

    def do_GET(self):
        # Railway needs an unauthenticated health endpoint; expose no data there.
        if urlsplit(self.path).path=='/healthz':
            self._response({'status':'ok'})
            return
        if not self._authorized(): return
        try:
            path=urlsplit(self.path).path
            q=self._query()
            if path=='/api/v108/management-options':
                with closing(connect()) as db:
                    a=feedback_options(q,True)
                    self._json(feedback.management_filter_options(db,**a))
            elif path=='/api/v107/qc':
                with closing(connect()) as db:self._json(feedback.qc(db))
            elif path=='/api/v107/stats':
                with closing(connect()) as db:self._json(feedback.stats(db,**feedback_options(q,True)))
            elif path=='/api/v107/comments':
                with closing(connect()) as db:
                    self._json(feedback.comments(db,**feedback_options(q,True),page=q.get('page',1),size=q.get('size',20)))
            elif path=='/api/v107/export':
                with closing(connect()) as db:content=feedback.export(db,**feedback_options(q,True))
                self._response(content,ctype='text/csv; charset=utf-8',
                    extra={'Content-Disposition':'attachment; filename="NHIS_V107_FILTERED_FEEDBACK_SCREEN.csv"'})
            elif path=='/api/local/status':
                self._json({'connected':False,'models':[],'model_info':{},'hosted_evidence_only':True,'estimated_spend_today_usd':0,'requests_today':0,'daily_budget_usd':0} if HOSTED else local_models())
            elif path=='/api/semantic/status':
                with closing(connect()) as db:
                    coded=db.execute("SELECT COUNT(*) FROM semantic_status WHERE status IN ('ok','partial_attachment')").fetchone()[0]
                    uncoded=db.execute("SELECT COUNT(*) FROM semantic_status WHERE status='awaiting_attachment'").fetchone()[0]
                    flagged=db.execute("SELECT COUNT(*) FROM semantic_status WHERE needs_review=1 OR status!='ok'").fetchone()[0]
                    no_attachment=db.execute("SELECT COUNT(*) FROM semantic_status s WHERE s.status='ok' AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.comment_id=s.comment_id)").fetchone()[0]
                    body_attachment=db.execute("SELECT COUNT(*) FROM comments c WHERE EXISTS (SELECT 1 FROM attachments a WHERE a.comment_id=c.comment_id)").fetchone()[0]
                    themes=[dict(x) for x in db.execute('''SELECT t.theme_id,COUNT(*) AS count,COUNT(DISTINCT cl.cluster_id) AS group_count
                            FROM semantic_tags t LEFT JOIN comment_clusters cl ON cl.comment_id=t.comment_id
                            GROUP BY t.theme_id ORDER BY count DESC''')]
                    self._json({'coded':coded,'corpus':db.execute('SELECT COUNT(*) FROM comments').fetchone()[0],
                                'uncoded_attachment':uncoded,'attachment_comment_records':body_attachment,
                                'coded_without_attachments':no_attachment,'need_review':flagged,
                                'themes':[] if HOSTED else themes,'counts_validated':False,
                                'warning':('All comment records were model-coded using cluster-consistent coding, but results have not been independently validated. Do not interpret raw theme counts as support prevalence.' if not uncoded else f'{uncoded} records await model coding; theme counts are provisional and not validated.')})
            elif path=='/api/semantic/download':
                kind=q.get('kind','counts')
                if HOSTED and kind=='counts':
                    self._json({'error':'Unvalidated AI theme frequencies are withheld from the management demo.'},403)
                    return
                with closing(connect()) as db: content=sem_csv(db,kind)
                filename={'counts':'ai_provisional_theme_counts.csv','assignments':'ai_theme_assignments.csv',
                          'review_queue':'ai_review_queue.csv'}[kind]
                self._response(content,ctype='text/csv; charset=utf-8',
                     extra={'Content-Disposition':f'attachment; filename={filename}'})
            elif path=='/api/source':
                self._json({'path':'Read-only hosted demo','available':False,'files':{}} if HOSTED else source_status())
            elif path=='/api/meta':
                with closing(connect()) as db:self._json({**metadata(db),'llm_enabled':(not HOSTED and bool(os.environ.get('OPENAI_API_KEY','').strip())),'hosted_readonly':READ_ONLY,'private_preview':PRIVATE_PREVIEW})
            elif path=='/api/qc':
                with closing(connect()) as db:self._json(analysis_qc(db))
            elif path=='/api/management_brief':
                with closing(connect()) as db:report=management_html(db)
                self._response(report,ctype='text/html; charset=utf-8',extra={'Content-Disposition':'attachment; filename=nhis_internal_qc_brief.html'})
            elif path=='/api/management':
                with closing(connect()) as db:
                    state=management.load(db)
                    state.pop('assignments',None)  # never transfer all assignment records on overview
                    self._json(state)
            elif path=='/api/management/comments':
                with closing(connect()) as db:
                    state=management.load(db)
                    self._json(feedback.comments(db,**feedback_options(q,True),page=q.get('page',1),size=q.get('size',20))
                        if feedback_requested(q) else
                        management.page(db,state,q.get('section','summary'),q.get('theme',''),
                              q.get('q',''),q.get('page','1'),q.get('size','20'),q.get('questionnaire','')))
            elif path=='/api/management/export':
                with closing(connect()) as db:
                    content=(feedback.export(db,**feedback_options(q,True)) if feedback_requested(q) else
                             management.csv_export(db,management.load(db),q.get('section',''),q.get('theme',''),q.get('q',''),q.get('questionnaire','')))
                self._response(content,ctype='text/csv; charset=utf-8',
                    extra={'Content-Disposition':'attachment; filename="nhis_management_multilabel.csv"'})
            elif path=='/api/management/topic-export':
                with closing(connect()) as db: state=management.load(db)
                if not state['ready']:self._json({'error':'Topic summary CSV not available'},409);return
                self._response(management.COMBO_CSV.read_bytes(),ctype='text/csv; charset=utf-8',
                    extra={'Content-Disposition':'attachment; filename="NHIS_MGMT_BY_AI_THEME_OFFLINE_COMPILED.csv"'})
            elif path=='/api/management/topic-report':
                with closing(connect()) as db: state=management.load(db)
                if not state['ready']:self._json({'error':'Topic summary Word appendix not available'},409);return
                self._response(management.COMBO_REPORT.read_bytes(),
                    ctype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    extra={'Content-Disposition':'attachment; filename="NHIS_MGMT_BY_AI_THEME_OFFLINE_COMPILED.docx"'})
            elif path=='/api/management/coded-export':
                # Complete, precomputed comment-level CSV: legacy themes + all management
                # codes and QC flags. Never use the local/private master DB.
                with closing(connect()) as db: state=management.load(db)
                if not state['ready']:
                    self._json({'error':'Management coded export unavailable before review gate'},409);return
                csvpath=ASSETS.parent/'qc_exports'/'NHIS_3748_V10_4_ADJUDICATED.csv'
                if not csvpath.is_file():
                    self._json({'error':'Full coded CSV missing'},409);return
                self._response(csvpath.read_bytes(),ctype='text/csv; charset=utf-8',
                    extra={'Content-Disposition':'attachment; filename="NHIS_3748_FULL_CODED_AI_THEMES_MANAGEMENT_QC.csv"'})
            elif path=='/api/management/report':
                import hashlib
                with closing(connect()) as db: state=management.load(db)
                if not state['ready']:self._json({'error':'Reviewed management report not yet available'},409);return
                expected=json.loads(management.ARTIFACT.read_text(encoding='utf-8')).get('report_sha256','')
                if not management.REPORT.is_file() or not expected or hashlib.sha256(management.REPORT.read_bytes()).hexdigest()!=expected:
                    self._json({'error':'Precomputed management report missing or does not match reviewed artifact'},409);return
                self._response(management.REPORT.read_bytes(),
                  ctype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                  extra={'Content-Disposition':'attachment; filename="nhis_management_classification_report.docx"'})
            elif path=='/api/themes':
                with closing(connect()) as db:
                    if feedback_requested(q):
                        base=theme_summary(db)
                        idx,ids,_=feedback.filter_result(db,**feedback_options(q,False))
                        selections=set(ids)
                        for t in base:
                            t['unfiltered_count']=t['count']
                            t['count']=len(idx['themes'].get(t['id'],set()) & selections)
                        base.sort(key=lambda x:(-x['count'],x['name']))
                        self._json({'themes':base,'method':'V10.7 filtered displayed-unit counts; legacy counts retained in unfiltered_count; provisional screening only.'})
                    else:self._json({'themes':theme_summary(db),'method':'Unvalidated keyword-screening tags; review before management use.'})
            elif path=='/api/comments':
                with closing(connect()) as db:
                    self._json(feedback.comments(db,**feedback_options(q,False),page=q.get('page',1),size=q.get('size',20))
                               if feedback_requested(q) else
                               list_comments(db,theme=q.get('theme'),phrase=q.get('q'),query_mode=q.get('match','any'),page=int(q.get('page',1)),size=int(q.get('size',20))))
            elif path.startswith('/api/comment/'):
                cid=path[len('/api/comment/'):]
                with closing(connect()) as db:
                    row=db.execute('SELECT * FROM comments WHERE comment_id=?',(cid,)).fetchone()
                    if row is None: self._json({'error':'Unknown comment'},404);return
                    d=dict(row);d.pop('normalized_sha',None)
                    d['themes']=theme_details(db,cid)
                    r=db.execute('SELECT review_status,notes,updated_utc FROM analyst_reviews WHERE comment_id=?',(cid,)).fetchone()
                    d['analyst_review']=dict(r) if r else {'review_status':'Not reviewed','notes':'','updated_utc':''}
                    d['attachments']=[dict(r) for r in db.execute('SELECT * FROM attachments WHERE comment_id=?',(cid,))]
                    cl=db.execute('SELECT cluster_id,cluster_size,personalized,unfilled_placeholder,novel_words FROM comment_clusters WHERE comment_id=?',(cid,)).fetchone()
                    d['cluster']=dict(cl) if cl else None
                    if d['cluster'] and d['cluster']['cluster_size']>1:
                        d['cluster'].update(cluster_subjects(db).get(d['cluster']['cluster_id'], {
                            'subject':'Subject not yet reviewed',
                            'subject_summary':'Review representative comment before assigning a subject.'}))
                    d['attachment_text']=[dict(r) for r in db.execute('SELECT attachment_id,format,status,chars,method FROM attachment_text WHERE comment_id=?',(cid,))]
                    d['v107']=feedback.index(db)['items'].get(cid)
                    self._json(d)
            elif path=='/api/export':
                kind=q.get('kind','')
                with closing(connect()) as db:
                    csv=(feedback.export(db,**feedback_options(q,False)) if feedback_requested(q) and kind=='query_matches'
                         else export_report(db,kind,theme=q.get('theme'),phrase=q.get('q'),query_mode=q.get('match','any')))
                    prefix='SYNTHETIC_TEST_' if metadata(db)['mode']=='synthetic demo' else ''
                self._response(csv,ctype='text/csv; charset=utf-8',extra={'Content-Disposition':f'attachment; filename="{prefix}nhis_{kind}.csv"'})
            elif path in ('/','/index.html','/style.css','/app.js','/v107.js','/v108_management.js'):
                name='index.html' if path=='/' else path[1:]
                mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
                self._response((ASSETS/name).read_bytes(),ctype=mime)
            else: self._json({'error':'Not found'},404)
        except Exception as exc:
            print('GET request failed:',type(exc).__name__,str(exc),file=sys.stderr)
            self._json({'error':'Request could not be completed'} if HOSTED else {'error':str(exc)},400)

    def do_POST(self):
        if not self._authorized(): return
        path=urlsplit(self.path).path
        if READ_ONLY and path not in READ_ONLY_ALLOWED_POSTS:
            self._json({'error':'This dashboard is read-only. Database edits are disabled.'},403)
            return
        try:
            self._check_local_origin()
            payload=self._body()
            if path=='/api/local/query':
                if not isinstance(payload,dict):raise ValueError('Expected JSON object')
                if READ_ONLY and (payload.get('model') or payload.get('approved')):raise ValueError('Hosted demo supports evidence-only queries; paid model calls are disabled')
                with closing(connect()) as db:result=local_answer(db,str(payload.get('question','')),str(payload.get('theme_id','')),str(payload.get('model','')),approved=payload.get('approved') is True,feedback_filter=payload.get('v107'))
                self._json(result)
            elif path=='/api/local/compare':
                if not isinstance(payload,dict):raise ValueError('Expected JSON object')
                with closing(connect()) as db:result=compare_theme(db,payload.get('draft',''),str(payload.get('theme_id','')),str(payload.get('model','')),approved=payload.get('approved') is True)
                self._json(result)
            elif path=='/api/sync':
                if payload.get('confirm') is not True:raise ValueError('Explicit synchronization confirmation required')
                backup_database()
                with closing(connect()) as db:result=sync_from_folder(db)
                self._json({'ok':True,**result})
            elif path=='/api/import':
                backup_database()
                with closing(connect()) as db:
                    result=import_data(db,payload.get('comments_csv',''),payload.get('attachments_csv',''),
                                       payload.get('index_json',''),payload.get('status_json',''),mode='real',
                                       allow_smaller=payload.get('allow_smaller') is True)
                self._json({'ok':True,**result})
            elif path=='/api/override':
                with closing(connect()) as db: result=save_override(db,str(payload.get('comment_id','')),
                                             str(payload.get('theme_id','')),int(payload.get('decision',-1)))
                self._json({'ok':True,**result})
            elif path=='/api/analyst_review':
                with closing(connect()) as db:result=save_analyst_review(db,str(payload.get('comment_id','')),
                    str(payload.get('review_status','')),payload.get('notes',''))
                self._json({'ok':True,**result})
            elif path=='/api/review':
                with closing(connect()) as db: result=response_review(db,payload.get('draft',''))
                self._json(result)
            elif path=='/api/export_review':
                with closing(connect()) as db:
                    content=export_report(db,'response_gap_review',draft=payload.get('draft',''))
                    prefix='SYNTHETIC_TEST_' if metadata(db)['mode']=='synthetic demo' else ''
                self._response(content,ctype='text/csv; charset=utf-8',extra={'Content-Disposition':f'attachment; filename="{prefix}nhis_response_review.csv"'})
            else:self._json({'error':'Unknown endpoint'},404)
        except Exception as exc:
            print('Request error:',exc,file=sys.stderr)
            self._json({'error':'Request could not be completed'} if HOSTED else {'error':str(exc)},400)


def backup_database():
    """Atomic SQLite backup before imports; keep only last 3 local snapshots."""
    if not DB_PATH.exists():return None
    from datetime import datetime, timezone
    import sqlite3
    import shutil
    folder=DB_PATH.parent/'backups'
    folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=folder/f'comments_before_import_{stamp}.sqlite3'
    # Avoid collisions when multiple imports happen in the same second.
    if path.exists():path=folder/f'comments_before_import_{stamp}_{os.getpid()}.sqlite3'
    with closing(connect()) as src:
        with closing(sqlite3.connect(str(path))) as dst:src.backup(dst)
    previous=sorted(folder.glob('comments_before_import_*.sqlite3'))
    for old in previous[:-3]:old.unlink(missing_ok=True)
    return path


def main():
    p=argparse.ArgumentParser(description='NHIS Comment Dashboard — local prototype')
    p.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765')))
    p.add_argument('--no-browser',action='store_true',help='Start server without launching browser')
    p.add_argument('--sync',action='store_true',help='Refresh from SOURCE_FOLDER.txt and exit')
    p.add_argument('--import-csv',help='Cumulative comments.csv path, import and exit')
    p.add_argument('--attachments',help='Attachments CSV path (only with --import-csv)')
    p.add_argument('--index',help='comment_index.json path')
    p.add_argument('--status',help='export_status.json path')
    p.add_argument('--rebuild',action='store_true',help='Re-derive cleaned text, theme tags and form-letter clusters from stored raw text, then exit')
    args=p.parse_args()
    if READ_ONLY and (args.rebuild or args.sync or args.import_csv):
        raise SystemExit('Hosted snapshot is read-only: import/rebuild disabled')
    if args.rebuild:
        backup_database()
        with closing(connect()) as db:
            print(json.dumps(rebuild_derived(db),indent=2))
        return
    if args.sync:
        backup_database()
        with closing(connect()) as db:
            print(json.dumps(sync_from_folder(db),indent=2))
        return
    if args.import_csv:
        backup_database()
        def read(p):return Path(p).read_text(encoding='utf-8-sig') if p else ''
        with closing(connect()) as db:
            print(json.dumps(import_data(db,read(args.import_csv),read(args.attachments),read(args.index),read(args.status)),indent=2))
        return
    if READ_ONLY:
        problem=hosted_snapshot_problem()
        if problem:raise SystemExit('Read-only snapshot not ready: '+problem)
    with closing(connect()) as db:
        rebuilt=None if READ_ONLY else ensure_derived_current(db)
        if rebuilt:print('Derived fields rebuilt for new cleaning/taxonomy version:',rebuilt)
        # Run before binding the listener: immutable hosted/local preview cannot repair stale FTS.
        from local_analysis import ensure_search_index, assert_search_index_complete
        if READ_ONLY: assert_search_index_complete(db)
        if HOSTED:
            v107=feedback.qc(db)
            if not v107['ready']:raise SystemExit('V10.7 regression gate failed: '+str(v107))
            print('V10.7 feedback gate:',v107['version'],v107['display_counts'])
        else: ensure_search_index(db)
        print('Local database:',DB_PATH,'records:',metadata(db)['records'])
    if HOSTED and not PUBLIC_DEMO and (not os.environ.get('DEMO_USER') or len(os.environ.get('DEMO_PASSWORD',''))<16):
        raise SystemExit('Hosted mode requires DEMO_USER and a DEMO_PASSWORD of at least 16 characters')
    host='0.0.0.0' if HOSTED else '127.0.0.1'
    srv=ThreadingHTTPServer((host,args.port),Handler)
    print(f'Dashboard listening on {host}:{args.port} (Ctrl+C to stop)')
    if not args.no_browser and not HOSTED:
        try:webbrowser.open(f'http://127.0.0.1:{args.port}')
        except Exception:pass
    try:srv.serve_forever()
    except KeyboardInterrupt:print('\nDashboard stopped. Your data remains saved.')
    finally:srv.server_close()

if __name__=='__main__': main()
