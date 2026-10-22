"""Read-only, additive management reporting over a separately reviewed, versioned artifact.

No model calls; no DB writes; no inference of categories from old provisional themes.
This module NEVER runs against the private master unless explicitly staged on a private copy.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / 'data' / 'management_artifact.json'
REPORT = ROOT / 'data' / 'management_report.docx'
COMBO = ROOT / 'data' / 'management_topic_summaries.json'
COMBO_CSV = ROOT / 'qc_exports' / 'MANAGEMENT_CATEGORY_TOPIC_COMPILED_SUMMARIES.csv'
COMBO_REPORT = ROOT / 'data' / 'management_topic_summaries_appendix.docx'
HEADINGS = (
    ('support', 'Support for the goals of the redesign', 'category'),
    ('criticism', 'Criticism of the goals of the redesign', 'category'),
    ('summary', 'Summary', 'overall'),
    ('requests', 'Requests for information', 'category'),
    ('process', 'Process', 'category'),
    ('content', 'Content', 'category'),
    ('other', 'Other comments', 'category'),
    ('questionnaire', 'Section-by-section summary of questionnaire decisions (pending further testing)', 'questionnaire'),
)
ALLOWED = {s[0] for s in HEADINGS}
LABELS = {s[0]: s[1] for s in HEADINGS}


def fingerprint(db):
    """Bind artifacts to comment IDs AND full-text/attachment AI source hashes."""
    h = hashlib.sha256()
    try:
        rows = db.execute('''SELECT c.comment_id,s.source_sha FROM comments c
           LEFT JOIN semantic_status s ON c.comment_id=s.comment_id ORDER BY c.comment_id''')
    except Exception as e:
        raise ValueError('Management snapshot requires AI source-status rows') from e
    n = 0
    for cid, sha in rows:
        h.update((cid+'\t'+(sha or '<PENDING>')+'\n').encode('utf-8'))
        n += 1
    return {'records':n,'source_fingerprint_sha256':h.hexdigest()}


def themes(db):
    lookup = {}
    f = ROOT/'themes.json'
    if f.is_file():
        try:lookup = {x['id']:x['name'] for x in json.loads(f.read_text(encoding='utf-8'))['themes']}
        except (KeyError,ValueError,TypeError):pass
    ids=sorted(set(lookup)|{r[0] for r in db.execute('SELECT DISTINCT theme_id FROM semantic_tags ORDER BY theme_id')})
    return [{'id':i,'name':lookup.get(i,i.replace('_',' ').capitalize())} for i in ids]


def section_shell():
    return [{'id':key,'name':name,'kind':kind,'count':None,'distinct_text_groups':None,
             'narrative':None,'subtopics':[],'evidence_ids':[], 'questionnaire_sections':[]} for key,name,kind in HEADINGS]


def load(db, artifact_path=ARTIFACT):
    """Fail closed when a missing/mismatched/unreviewed snapshot is encountered."""
    base={'ready':False,'status':'Awaiting frozen, reviewed management artifact',
          'sections':section_shell(),'themes':themes(db),'version':None,'corpus_records':None,
          'definition':'Counts are distinct comment records; overlaps across categories are permitted.'}
    if not artifact_path.is_file():return base
    try:
        artifact=json.loads(artifact_path.read_text(encoding='utf-8'))
        if artifact.get('schema_version')!=1:raise ValueError('Unsupported artifact schema')
        if artifact.get('section_order')!=[x[0] for x in HEADINGS]:raise ValueError('Missing/reordered management section')
        actual=fingerprint(db)
        if artifact.get('corpus')!=actual:raise ValueError('Artifact snapshot differs from the active database')
        preview = (artifact.get('status')=='machine_draft' and
                   os.getenv('NHIS_MANAGEMENT_PREVIEW','0')=='1' and
                   os.getenv('NHIS_READ_ONLY','0')=='1' and
                   os.getenv('NHIS_DEPLOYMENT_MODE','local').lower()!='hosted')
        # Explicit public-preview authorization. This does NOT claim human validation.
        # The UI always labels this corpus as provisional and provides the questionable-record QC export.
        public_provisional = (artifact.get('status')=='machine_draft' and
              os.getenv('NHIS_DEPLOYMENT_MODE','local').lower()=='hosted' and
              os.getenv('NHIS_PUBLIC_DEMO','0')=='1' and
              os.getenv('NHIS_READ_ONLY','0')=='1' and
              os.getenv('NHIS_ALLOW_PUBLIC_PROVISIONAL','0')=='1')
        if artifact.get('status')!='provisional_reviewed' and not preview and not public_provisional:
            raise ValueError('Artifact has not passed review gate')
        by_category=defaultdict(set)
        by_questionnaire=defaultdict(set)
        db_ids={r[0] for r in db.execute('SELECT comment_id FROM comments')}
        for r in artifact['assignments']:
            cid=r['comment_id'];c=r['category'];q=r.get('questionnaire_section','')
            if cid not in db_ids:raise ValueError('Classification references unknown comment')
            if c not in ALLOWED-{'summary','questionnaire'}:raise ValueError('Unsupported substantive management category')
            by_category[c].add(cid)
            if q:
                for section_name in [part.strip() for part in q.split(' | ') if part.strip()]:by_questionnaire[section_name].add(cid)
        for key,name,kind in HEADINGS:
            if key not in artifact['narratives']:raise ValueError('Missing whole-section synthesis: '+key)
        for key,source in artifact['narratives'].items():
            if key not in ALLOWED or not source.get('text') or not source.get('version'):
                raise ValueError('Missing or invalid versioned summary: '+key)
            matching=(set(db_ids) if key=='summary' else
                      set().union(*by_questionnaire.values()) if key=='questionnaire' else by_category[key])
            if not set(source.get('evidence_ids',[]))<=matching:
                raise ValueError('Narrative citations outside the selected section: '+key)
        groups={r['comment_id']:r['cluster_id'] for r in db.execute('SELECT comment_id,cluster_id FROM comment_clusters')}
        topic_counts=defaultdict(Counter)
        for r in artifact['assignments']:
            if r.get('subtopic'):topic_counts[r['category']][r['subtopic']]+=1
        sections=[]
        for key,name,kind in HEADINGS:
            ids=(db_ids if key=='summary' else
                 set().union(*by_questionnaire.values()) if key=='questionnaire' else by_category[key])
            synopsis=artifact['narratives'][key]
            sections.append({'id':key,'name':name,'kind':kind,'count':len(ids),
                'distinct_text_groups':len({groups.get(cid,cid) for cid in ids}),
                'narrative':synopsis['text'],
                'compiled_arguments':(artifact.get('synthesis_details',{}).get(key,{}) or {}).get('code_rows',[]),
                'compiled_top_clusters':(artifact.get('synthesis_details',{}).get(key,{}) or {}).get('top_clusters',[]),
                'coding_rule_description':(artifact.get('synthesis_details',{}).get(key,{}) or {}).get('coding_rule_description',''),
                'coding_rule_code_rows':(artifact.get('synthesis_details',{}).get(key,{}) or {}).get('coding_rule_code_rows',[]),
                'category_overlap':artifact.get('coding_framework_notes',{}).get('overlap',{}),
                'synthesis_scope':artifact.get('synthesis_scope','Full section narrative; filters do not change it'),
                'agency_response_status':artifact.get('agency_response_status','Agency decision pending clearance'),
                'narrative_version':synopsis['version'],
                'narrative_review':synopsis.get('review_status','provisional'),
                'evidence_ids':synopsis['evidence_ids'],
                'subtopics':[{'name':n,'assignment_rows':count} for n,count in topic_counts[key].most_common()],
                'questionnaire_sections':[{'name':n,'count':len(v)} for n,v in sorted(by_questionnaire.items())] if key=='questionnaire' else []})
        if Path(artifact_path).resolve()==ARTIFACT.resolve():
            # Fail closed if precomputed combinations differ from the frozen coding source.
            if not COMBO.is_file():raise ValueError('Precompiled management/topic synthesis missing')
            comp=json.loads(COMBO.read_text(encoding='utf-8'))
            if comp.get('source_corpus_fingerprint')!=actual:raise ValueError('Topic synthesis is from another source snapshot')
            if comp.get('category_ids')!=[x[0] for x in HEADINGS] or set(comp.get('topic_ids',[]))!={x['id'] for x in base['themes']}:
                raise ValueError('Topic synthesis categories or themes do not match the active database')
            combo=comp.get('combinations',{})
            if len(combo)!=8*len(base['themes']):raise ValueError('Incomplete category/theme synthesis matrix')
            # Check each topic intersection against both existing tag tables, not the saved count alone.
            theme_ids=defaultdict(set)
            for cid,tid in db.execute('SELECT comment_id,theme_id FROM semantic_tags'):
                theme_ids[tid].add(cid)
            for key,name,kind in HEADINGS:
                category_ids=(db_ids if key=='summary' else
                    set().union(*by_questionnaire.values()) if key=='questionnaire' else by_category[key])
                for topic in theme_ids:
                    row=combo.get(key+'::'+topic)
                    if not row or row.get('comment_count')!=len(category_ids & theme_ids[topic]):
                        raise ValueError('Precompiled topic count is stale: '+key+'/'+topic)
                    if not set(row.get('source_ids',[]))<=category_ids & theme_ids[topic]:
                        raise ValueError('Topic synthesis cites unrelated source: '+key+'/'+topic)
            if not COMBO_CSV.is_file() or not COMBO_REPORT.is_file():
                raise ValueError('Topic matrix downloads are missing')
            if hashlib.sha256(COMBO_CSV.read_bytes()).hexdigest()!=comp.get('csv_sha256') or hashlib.sha256(COMBO_REPORT.read_bytes()).hexdigest()!=comp.get('report_sha256'):
                raise ValueError('Precompiled topic downloads failed checksum verification')
            base['topic_combinations']=combo
            base['topic_synthesis_info']={k:comp[k] for k in ('version','matrix_size','nonempty_combinations','empty_combinations','method','limitations')}
        base.update({'ready':True,'status':('AI-ADJUDICATED PROVISIONAL — 62 questionable records; local-only preview, not human-validated or an agency response' if preview else 'Public AI-assisted provisional synthesis · NOT independently validated · 62 questionable records' if public_provisional else 'Provisional · review required before agency attribution'), 'machine_draft':bool(preview or public_provisional),
                     'sections':sections,'version':artifact['version'],
                     'corpus_records':actual['records'],'corpus':actual,
                     'public_inventory_checked_utc':artifact.get('public_inventory_checked_utc',''),
                     'assignment_records':len({r['comment_id'] for r in artifact['assignments']}),
                     'assignments':artifact['assignments']})
    except (ValueError,KeyError,TypeError, OSError) as exc:
        base['status']='Artifact unavailable: '+str(exc)
    return base


def page(db, state, category, theme='', query='', page_number=1, page_size=20, questionnaire_section=''):
    if not state['ready']:return {'ready':False,'total':None,'rows':[]}
    if category not in ALLOWED:raise ValueError('Unknown management reporting section')
    valid_themes={t['id'] for t in state['themes']}
    if theme and theme not in valid_themes:raise ValueError('Unknown provisional AI theme')
    if len(query)>300:raise ValueError('Search phrase exceeds allowed length')
    page_number=max(1,min(int(page_number),100000));page_size=max(1,min(int(page_size),100))
    assignments=state['assignments']
    ids={r['comment_id'] for r in assignments if (category=='questionnaire' and r.get('questionnaire_section')) or r['category']==category}
    if category=='summary':ids={r[0] for r in db.execute('SELECT comment_id FROM comments')}
    if questionnaire_section and category=='questionnaire':
        ids &= {r['comment_id'] for r in assignments if questionnaire_section in [part.strip() for part in r.get('questionnaire_section','').split(' | ')]}
    if theme:
        ids &= {r[0] for r in db.execute('SELECT comment_id FROM semantic_tags WHERE theme_id=?',(theme,))}
    if query.strip():
        terms=query.strip().casefold()
        ids &= {r['comment_id'] for r in db.execute('SELECT comment_id,plain_text,title,organization FROM comments')
                if any(terms in (r[k] or '').casefold() for k in ('plain_text','title','organization'))}
    total=len(ids)
    selected=sorted(ids)[(page_number-1)*page_size:page_number*page_size]
    rows=[]
    for cid in selected:
        r=db.execute('''SELECT c.comment_id,c.title,c.organization,c.posted_date,c.comment_url,
                         substr(c.plain_text,1,900) AS excerpt, cl.cluster_id,cl.cluster_size
                         FROM comments c LEFT JOIN comment_clusters cl ON c.comment_id=cl.comment_id
                         WHERE c.comment_id=?''',(cid,)).fetchone()
        item=dict(r)
        try:
            flagged=db.execute('SELECT management_low_confidence,management_low_confidence_reasons,management_review_status FROM coded_comments_final WHERE comment_id=?',(cid,)).fetchone()
        except sqlite3.OperationalError:
            flagged=None
        if flagged:
            item.update({'management_low_confidence':flagged[0], 'management_low_confidence_reasons':flagged[1], 'management_review_status':flagged[2]})
        rows.append(item)
    return {'ready':True,'section':category,'total':total,'page':page_number,'page_size':page_size,
            'rows':rows,'filters':{'theme':theme,'q':query,'questionnaire':questionnaire_section},
            'narrative_scope':'Full category. Filter changes count and records only.'}


def csv_export(db,state,category='',theme='',query='',questionnaire_section=''):
    """Export every assignment on selected records (or only selected section).

    Same eligibility rules as page(); no 100-row truncation or repeated N-page queries.
    Summary is a view over all records, not an additional substantive label.
    """
    if not state['ready']:raise ValueError('Management artifact is not yet available')
    if category and category not in ALLOWED:raise ValueError('Unknown section')
    if questionnaire_section and category != 'questionnaire':
        raise ValueError('Questionnaire filter requires questionnaire section view')
    valid_themes={t['id'] for t in state['themes']}
    if theme and theme not in valid_themes:raise ValueError('Unknown provisional AI theme')
    if len(query)>300:raise ValueError('Search phrase exceeds allowed length')
    all_assignments=state['assignments']
    selected_ids=None
    if category=='summary':
        selected_ids={r[0] for r in db.execute('SELECT comment_id FROM comments')}
    elif category=='questionnaire':
        selected_ids={r['comment_id'] for r in all_assignments if r.get('questionnaire_section') and
                      (not questionnaire_section or questionnaire_section in [part.strip() for part in r.get('questionnaire_section','').split(' | ')])}
    elif category:
        selected_ids={r['comment_id'] for r in all_assignments if r['category']==category}
    if theme:
        theme_ids={r[0] for r in db.execute('SELECT comment_id FROM semantic_tags WHERE theme_id=?',(theme,))}
        selected_ids=theme_ids if selected_ids is None else selected_ids & theme_ids
    if query.strip():
        q=query.strip().casefold()
        qids={r['comment_id'] for r in db.execute('SELECT comment_id,plain_text,title,organization FROM comments')
              if any(q in (r[col] or '').casefold() for col in ('plain_text','title','organization'))}
        selected_ids=qids if selected_ids is None else selected_ids & qids
    meta={r['comment_id']:(r['posted_date'],r['comment_url']) for r in db.execute('SELECT comment_id,posted_date,comment_url FROM comments')}
    out=io.StringIO(newline='');w=csv.writer(out)
    w.writerow(['comment_id','management_section','subtopic','questionnaire_section','review_status',
                'provisional_theme_filter','posted_date','comment_url','questionable_flag','questionable_reason'])
    for a in sorted(all_assignments,key=lambda r:(r['comment_id'],r['category'],r.get('subtopic',''))):
        if selected_ids is not None and a['comment_id'] not in selected_ids:continue
        if category not in ('','summary') and category!='questionnaire' and a['category']!=category:continue
        if category=='questionnaire' and (not a.get('questionnaire_section') or (questionnaire_section and a.get('questionnaire_section')!=questionnaire_section)):continue
        posted,url=meta[a['comment_id']]
        try:
            flag=db.execute('SELECT management_low_confidence,management_low_confidence_reasons FROM coded_comments_final WHERE comment_id=?',(a['comment_id'],)).fetchone()
        except sqlite3.OperationalError:
            flag=None
        w.writerow([a['comment_id'],a['category'],a.get('subtopic',''),a.get('questionnaire_section',''),
                    a.get('review_status','provisional'),theme or '',posted,url,flag[0] if flag else '',flag[1] if flag else ''])
    return out.getvalue().encode('utf-8-sig')
