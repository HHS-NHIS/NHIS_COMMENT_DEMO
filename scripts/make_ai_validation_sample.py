#!/usr/bin/env python3
"""Generate blinded AI theme-coding sample and a SEPARATE, never-public scoring key.

Stratified random sample of comment-theme pairs: up to 8 AI-positive and 8 AI-negative
records per theme. Sampling without replacement within each stratum; fixed seed makes
this exactly reproducible. Counts of comments, not unique commenters or people.
The KEY exposes model labels and must never be shared with blinded human coders.
"""
from __future__ import annotations
import argparse,csv,json,random,sqlite3
from contextlib import closing
from pathlib import Path

def write_csv(path,rows,columns):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)

def make(db_path,themes_path,coder_path,key_path,seed=20261020,n_each=8):
    if Path(coder_path).resolve() == Path(key_path).resolve(): raise ValueError('Key and coder file MUST differ')
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory=sqlite3.Row
        records=[dict(r) for r in db.execute('SELECT comment_id,plain_text,comment_url FROM comments ORDER BY comment_id')]
        labels={(r['comment_id'],r['theme_id']) for r in db.execute('SELECT comment_id,theme_id FROM semantic_tags')}
    themes=json.loads(Path(themes_path).read_text(encoding='utf8'))['themes']
    rng=random.Random(seed); sample=[]; key=[]
    for theme in themes:
        tid=theme['id']; ids={r['comment_id'] for r in records if (r['comment_id'],tid) in labels}
        for positive in (True,False):
            pool=[r for r in records if (r['comment_id'] in ids)==positive]
            chosen=rng.sample(pool,min(n_each,len(pool)))
            for c in chosen:
                rid=f'AI{len(sample)+1:04d}'; stratum='screen_positive' if positive else 'screen_negative'
                sample.append({'review_id':rid,'comment_id':c['comment_id'],'theme_id':tid,
                               'theme':theme['name'],'theme_definition':theme.get('description',''),
                               'source_url':c['comment_url'],'comment_excerpt':(c['plain_text'] or '')[:4000],
                               'human_label':'','human_label_2':'','coder_notes':''})
                key.append({'review_id':rid,'comment_id':c['comment_id'],'theme_id':tid,
                            'stratum':stratum,'stratum_population':len(pool),'model_label':int(positive)})
    # Shuffle review order to prevent coders inferring the two strata from row position.
    ix=list(range(len(sample)));rng.shuffle(ix)
    sample=[sample[i] for i in ix]
    write_csv(coder_path,sample,['review_id','comment_id','theme_id','theme','theme_definition',
                                  'source_url','comment_excerpt','human_label','human_label_2','coder_notes'])
    write_csv(key_path,key,['review_id','comment_id','theme_id','stratum','stratum_population','model_label'])
    return {'rows':len(sample),'themes':len(themes),'key_file_is_private':str(key_path),'coder_file':str(coder_path)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='data/comments.sqlite3');p.add_argument('--themes',default='themes.json')
    p.add_argument('--coder',default='HUMAN_CODER_SAMPLE_AI_LABELS.csv')
    p.add_argument('--key',required=True,help='Separate private key; never commit this file to public GitHub')
    p.add_argument('--seed',type=int,default=20261020);p.add_argument('--per-stratum',type=int,default=8)
    a=p.parse_args();print(json.dumps(make(a.db,a.themes,a.coder,a.key,a.seed,a.per_stratum),indent=2))
if __name__=='__main__': main()
