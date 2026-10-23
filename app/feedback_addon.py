"""Read-only supplemental facets for management feedback (screening, not validation).
All functions query the frozen database; no schema writes, AI calls or new dependencies.
"""
import csv, io, re
from collections import Counter, defaultdict

MODES=('all','representative','exclude')
TOPICS=(
 ('tobacco','Tobacco, nicotine and cigarettes',r'\b(?:tobacco|nicotine|cigarettes?|smoking|vaping|e-cigarettes?)\b'),
 ('alcohol','Alcohol use',r'\b(?:alcohol|drinking|binge drinking)\b'),
 ('screening','Cancer and chronic-condition screening',r'\b(?:cancer screening|mammograph\w*|colonoscopy|colorectal screening|screening for (?:cancer|chronic|diabetes)|preventive screening)\b'),
 ('cardiovascular','Cardiovascular and heart health',r'\b(?:cardiovascular|coronary|heart disease|heart failure|heart health|hypertension|blood pressure)\b'),
 ('asthma','Asthma',r'\basthma\b'),
 ('diabetes','Diabetes',r'\b(?:diabetes|diabetic|blood sugar|glycemic)\b'),
 ('medications','Medications and prescriptions',r'\b(?:medicat\w*|prescrip\w*|pharmac\w*|drug adherence)\b'),
 ('services','Health care services and visits',r'\b(?:health\s?care visits?|doctor visits?|physician visits?|medical appointments?|outpatient visits?|hospital visits?|health services utilization)\b'),
 ('insurance','Insurance and coverage measures',r'\b(?:health insurance|insurance coverage|uninsured|underinsured|medicare|medicaid|coverage type|insurance status|health plan|premiums?)\b'),
 ('costs','Health care costs',r'\b(?:out.of.pocket|medical costs?|health\s?care costs?|cost of care|medical bills?|affordability of (?:care|treatment)|health expenses?)\b'),
 ('wphi','Whole Person Health / WPHI',r'\b(?:WPHI|whole.person health|whole person health index)\b'),
 ('loneliness','Loneliness, connectedness and social isolation',r'\b(?:lonelin\w*|social isolat\w*|social connected\w*|social connection|social support)\b'),
 ('physical_activity','Physical activity',r'\b(?:physical activity|exercise|sedentary|fitness)\b'),
 ('sleep','Sleep',r'\b(?:sleep|insomnia|sleep apnea|sleep quality)\b'),
 ('demographic','Demographic measures',r'\b(?:demographic measures?|race(?:/| and )ethnicity questions?|race or ethnicity questions?|ethnic origin|sex assigned at birth|sexual orientation questions?|gender identity questions?|age categories|race categories|demographic questions?)\b'),
)
ACTIONS=(
 ('retain','Retain or restore removed measures',r'\b(?:retain|restore|reinstate|keep|preserve|do not remove|should not be removed)\b'),
 ('add','Add measures or topics',r'\b(?:add|include|incorporate|introduce|new (?:question|measure|item)|should measure|should include)\b'),
 ('remove','Remove or reduce content',r'\b(?:remove|delete|drop|reduce|shorten|eliminate|omit|should not (?:ask|include))\b'),
 ('revise','Revise wording, skips, universes or responses',r'\b(?:reword|wording|response options?|answer choices?|skip patterns?|skip logic|universe|universes|who is asked|revise the question)\b'),
)
INTENT=re.compile(r'\b(?:recommend|request|suggest|urge|support|oppose|should|must|please|retain|restore|include|add|remove|delete|change|revise|measure|ask about|collect data)\b',re.I)
ASSOC=re.compile(r'\b(?:associated with|linked to|correlated with|comorbid|more likely to|risk factor for)\b',re.I)
SUPPORT=re.compile(r'\b(?:strongly support|support(?:s|ing|ed)?|endorse|commend|would (?:love|like) to see|is crucial|is important|is essential|should be (?:included|integrated|retained))\b',re.I)
OBJECT=re.compile(r'\b(?:whole.person health|WPHI|measure|question(?:s|naire)?|item|index|topic|component|module|inclusion)\b',re.I)
_TOPIC_RX=[(code,name,re.compile(pattern,re.I)) for code,name,pattern in TOPICS]
_ACTION_RX=[(code,name,re.compile(pattern,re.I)) for code,name,pattern in ACTIONS]

def topic_labels(text):
    """Multiple primary topics permitted; incidental associations not treated as primary.
    Heuristic evidence only, not an independently validated classification.
    """
    found={}
    for code,name,rx in _TOPIC_RX:
        matches=list(rx.finditer(text))
        if not matches:continue
        first=matches[0].start()
        vicinity=text[max(0,first-140):first+170]
        intent=bool(INTENT.search(vicinity))
        incidental=bool(ASSOC.search(vicinity)) and not intent and len(matches)<3
        relevance=('incidental' if incidental else
                   'primary' if (len(matches)>=2 and (intent or first<800)) or (first<650 and intent)
                   else 'secondary')
        found[code]={'name':name,'relevance':relevance,'evidence':matches[0].group(0),'hits':len(matches)}
    return found

def content_actions(text):
    sentences=re.split(r'(?<=[.!?])\s+|\n+',text)
    codes=[code for code,name,rx in _ACTION_RX
           if any(rx.search(s) and (INTENT.search(s) or code=='revise') for s in sentences)]
    return codes or ['unclear']

def measure_support(text):
    # Explicit support for individual measures need not endorse the entire redesign.
    return any(SUPPORT.search(s) and OBJECT.search(s)
               for s in re.split(r'(?<=[.!?])\s+|\n+',text))

def build_index(db):
    """Indexes only public comment text and existing, successfully extracted attachments."""
    repeated={sha for sha,n in db.execute(
        "SELECT normalized_sha,COUNT(*) FROM comments WHERE normalized_sha IS NOT NULL AND normalized_sha<>'' GROUP BY normalized_sha HAVING COUNT(*)>1")}
    flags={}
    for cid,sha,txt,cluster,size,overlap,personalized in db.execute(
        """SELECT c.comment_id,c.normalized_sha,c.plain_text,cl.cluster_id,
                  cl.cluster_size,cl.overlap,cl.personalized
           FROM comments c LEFT JOIN comment_clusters cl ON c.comment_id=cl.comment_id"""):
        status='exact_repeated_text' if sha and sha in repeated else ('likely_form_letter' if (size or 1)>1 else 'not_flagged')
        flags[cid]={'status':status,'cluster_id':cluster or cid,'cluster_size':size or 1,
                    'overlap':overlap,'personalized':bool(personalized),'length':len(txt or '')}
    attachments=defaultdict(list)
    try:
        for cid,txt in db.execute("SELECT comment_id,text FROM attachment_text WHERE status='ok'"):
            if txt: attachments[cid].append(txt)
    except Exception:pass
    topics={};actions={};measure=set()
    for cid,title,txt in db.execute('SELECT comment_id,title,plain_text FROM comments'):
        text=(title or '')+'\n'+(txt or '')+'\n'+'\n'.join(attachments.get(cid,[]))
        topics[cid]=topic_labels(text)
        actions[cid]=content_actions(text)
        if measure_support(text):measure.add(cid)
    return {'flags':flags,'topics':topics,'actions':actions,'measure_support':measure}


# Hosted snapshots are immutable. Cache screening once per process to keep filters fast.
# Mutable local sessions deliberately re-read the database after each import.
_CACHED=None
def get_index(db):
    global _CACHED
    import os
    immutable=(os.environ.get('NHIS_DEPLOYMENT_MODE','local')=='hosted' or
               os.environ.get('NHIS_READ_ONLY','0')=='1')
    if immutable and _CACHED is not None:return _CACHED
    answer=build_index(db)
    if immutable:_CACHED=answer
    return answer

def select_ids(index,ids,mode='all'):
    if mode not in MODES:raise ValueError('Unknown repeated-submission mode')
    ids=set(ids); flags=index['flags']
    if mode=='all':return ids
    if mode=='exclude':return {cid for cid in ids if flags[cid]['status']=='not_flagged'}
    groups=defaultdict(list)
    for cid in ids:groups[flags[cid]['cluster_id']].append(cid)
    # Representative must be drawn from the matched set, and favors longer evidence.
    return {min(g,key=lambda cid:(-flags[cid]['length'],cid)) for g in groups.values()}

def summary(index,ids,mode='all',topic='',relevance='any',action=''):
    ids=set(ids)
    if topic:
        if topic not in {x[0] for x in TOPICS}:raise ValueError('Unknown exploratory topic')
        if relevance not in ('any','primary','secondary','incidental'):raise ValueError('Unknown relevance')
        ids={cid for cid in ids if topic in index['topics'][cid] and
             (relevance=='any' or index['topics'][cid][topic]['relevance']==relevance)}
    if action:
        if action not in {x[0] for x in ACTIONS}|{'unclear'}:raise ValueError('Unknown content action')
        ids={cid for cid in ids if action in index['actions'][cid]}
    included=select_ids(index,ids,mode)
    count=Counter(index['flags'][cid]['status'] for cid in ids)
    # Dynamic, source-grounded screening digest for this exact filtered record set.
    # Not an AI-generated narrative and never substituted for management synthesis.
    primary=Counter()
    evid=defaultdict(list)
    for cid in sorted(included):
        for code,v in index['topics'][cid].items():
            if v['relevance']=='primary':
                primary[code]+=1
                if len(evid[code])<3:evid[code].append(cid)
    names={code:name for code,name,_ in TOPICS}
    top=[{'id':code,'name':names[code],'comment_records':n,'evidence_ids':evid[code]}
         for code,n in primary.most_common(8)]
    action_counts=Counter(code for cid in included for code in index['actions'][cid])
    return {'total_submissions':len(ids),'matching_records':len(included),
            'approximate_distinct_groups':len({index['flags'][cid]['cluster_id'] for cid in ids}),
            'exact_repeated_text':count['exact_repeated_text'],
            'likely_form_letter':count['likely_form_letter'],'not_flagged':count['not_flagged'],
            'personalized_in_matching':sum(index['flags'][cid]['personalized'] for cid in ids),
            'mode':mode,'ids':sorted(included),'top_primary_topics':top,
            'content_action_screen':dict(action_counts),
            'limitations':'All labels are provisional screening. Excluding form-letter groups may omit substantive personal additions. Original submission counts are preserved.'}

def filtered_csv(db,index,ids,mode='all',topic='',relevance='any',action=''):
    details=summary(index,ids,mode,topic,relevance,action)
    urls=dict(db.execute('SELECT comment_id,comment_url FROM comments'))
    output=io.StringIO(newline='');w=csv.writer(output)
    w.writerow(['comment_id','form_letter_flag','cluster_id','cluster_size','overlap',
                'personalized','exploratory_topic','relevance','content_actions','source_url'])
    for cid in details['ids']:
        flag=index['flags'][cid]
        matches=index['topics'][cid].items() or [('',{})]
        for topic_id,t in matches:
            w.writerow([cid,flag['status'],flag['cluster_id'],flag['cluster_size'],
                       flag['overlap'],int(flag['personalized']),topic_id,t.get('relevance',''),
                       '|'.join(index['actions'][cid]),urls.get(cid,'')])
    return output.getvalue().encode('utf-8-sig')
