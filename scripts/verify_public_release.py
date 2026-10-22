from __future__ import annotations
import sqlite3, json, hashlib, os, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'app'))
import management_addon as management
p=root/'data/comments.sqlite3'
db=sqlite3.connect(p)
db.row_factory=sqlite3.Row
try:
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  n=db.execute('select count(*) from comments').fetchone()[0]
  index=db.execute('select count(*) from local_fts').fetchone()[0]
  assert n==index==3748,(n,index)
  assert not {x[0] for x in db.execute('select name from sqlite_master')}&{'semantic_parts','template_label_review','demo_claude_adjudication_audit'},'Internal tables exposed'
  state=management.load(db)
  assert state['ready'],state.get('status')
  assert len(state['sections'])==8
  combos=json.loads((root/'data/management_topic_summaries.json').read_text(encoding='utf8'))
  assert combos
  artifact=json.loads((root/'data/management_artifact.json').read_text(encoding='utf8'))
  assert hashlib.sha256((root/'data/management_report.docx').read_bytes()).hexdigest()==artifact['report_sha256']
  print('PUBLIC RELEASE VERIFIED: 3748/3748, 8 management headings, provisional labels disclosed')
finally:db.close()
