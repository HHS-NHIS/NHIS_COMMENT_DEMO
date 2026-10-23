"""HTTP smoke checks against running read-only V10.7 server with 3,748 release."""
import csv, io, json, time
from urllib.request import urlopen
from urllib.parse import urlencode
BASE="http://127.0.0.1:8767"

def get(route,**params):
    u=BASE+route+('?' + urlencode(params) if params else '')
    with urlopen(u,timeout=30) as response:
        assert response.status==200,(u,response.status)
        return response.read(),response.headers.get("content-type","")

for n in range(45):
    try:
        body,_=get('/api/meta');break
    except Exception:
        if n==44:raise
        time.sleep(.5)
meta=json.loads(body)
assert meta['records']==3748,meta['records']
opts=json.loads(get('/api/feedback/options')[0])
assert opts['corpus']['total_submissions']==3748
assert len(opts['topics'])==15
assert len(opts['actions'])==5
for mode in ('all','representative','exclude'):
    d=json.loads(get('/api/feedback/records',form_mode=mode)[0])
    assert d['total_submissions']==3748,(mode,d['total_submissions'])
    assert d['matching_records']<=3748
    assert d['exact_repeated_text']+d['likely_form_letter']+d['not_flagged']==3748
    assert d['top_primary_topics'] is not None
mg=json.loads(get('/api/management')[0])
assert mg['ready'] and len(mg['sections'])==8
ts=json.loads(get('/api/themes')[0])
assert len(ts['themes'])==30
for route in ('/api/comments','/api/qc','/api/feedback/options','/api/management/topic-export'):
    get(route)
# Previous comments endpoint behavior remains unchanged at default all mode.
plain=json.loads(get('/api/comments',q='whole person health')[0])
all_mode=json.loads(get('/api/comments',q='whole person health',form_mode='all')[0])
assert plain['total']==all_mode['total']
exclude=json.loads(get('/api/comments',q='whole person health',form_mode='exclude')[0])
assert exclude['total']<=plain['total']
# Filtered explorer export count agrees with filtered explorer response.
csv_data,_=get('/api/export',kind='query_matches',q='whole person health',form_mode='exclude')
csv_rows=list(csv.DictReader(io.StringIO(csv_data.decode('utf-8-sig'))))
assert len(csv_rows)==exclude['total'],(len(csv_rows),exclude['total'])
# Explicit endorsements of a specific measure are discoverable under Support.
support=json.loads(get('/api/feedback/records',section='support',q='whole person health',size=100)[0])
ids={row['comment_id'] for row in support['rows']}
for tail in ('0414','0428','0518'):
    assert 'CDC-2026-1387-'+tail in ids,(tail,sorted(ids))
assert support['support_measure_overlay']
# Saved narratives remain versioned; supplementary filters only change evidence and counts.
filtered=json.loads(get('/api/feedback/records',section='content',topic='insurance',
                        relevance='primary',form_mode='representative')[0])
assert 'narrative_scope' in filtered and filtered['matching_records']<=filtered['total_submissions']
assert json.loads(get('/api/feedback/records',section='questionnaire',questionnaire='No such section')[0])['total']==0
# Export headers must identify supplemental support and form status explicitly.
data,_=get('/api/feedback/export',section='support',topic='wphi')
assert 'selected_management_view' in data.decode('utf-8-sig').splitlines()[0]
print('PASS V10.7 HTTP smoke: all legacy key routes, 3748 corpus, all form modes, topic filters, WPHI support, CSV alignment and management narrative scope')
