import csv, sqlite3, tempfile, unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import semantic_classify as sc
from build_public_snapshot import build
from make_ai_validation_sample import make

class V96ReleaseTests(unittest.TestCase):
 def test_master_not_changed_and_private_tables_not_published(self):
  with tempfile.TemporaryDirectory() as t:
   import shutil,hashlib
   root=Path(t); master=root/'master.sqlite3';shutil.copy2(ROOT/'data/comments.sqlite3',master)
   baseline=hashlib.sha256(master.read_bytes()).hexdigest()
   result=build(master,root/'output')
   self.assertEqual(result['comments'],1693)
   self.assertEqual(hashlib.sha256(master.read_bytes()).hexdigest(),baseline)
   public=sqlite3.connect(root/'output/data/comments.sqlite3')
   self.assertEqual(public.execute('pragma integrity_check').fetchone()[0],'ok')
   for name in ('semantic_parts','template_label_review','demo_claude_adjudication_audit'):
    self.assertFalse(public.execute('select name from sqlite_master where name=?',(name,)).fetchone())
   for name in ('analyst_reviews','imports','manual_overrides'):
    self.assertEqual(public.execute(f'select count(*) from {name}').fetchone()[0],0)
   self.assertEqual(public.execute('select count(*) from semantic_tags').fetchone()[0],8807)
   public.close()
 def test_private_validation_key_and_blinded_sample(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);out=make(ROOT/'data/comments.sqlite3',ROOT/'themes.json',p/'coder.csv',p/'SECRET.csv')
   self.assertEqual(out['rows'],477)
   with (p/'coder.csv').open(encoding='utf-8-sig') as f:coder=list(csv.DictReader(f))
   with (p/'SECRET.csv').open(encoding='utf-8-sig') as f:key=list(csv.DictReader(f))
   self.assertEqual(len(coder),len(key))
   self.assertFalse(any('model_label' in r or 'stratum' in r for r in coder))
   self.assertTrue(all(not r['human_label'] for r in coder))
   self.assertEqual(len(set(r['review_id'] for r in coder)),477)
 def test_template_review_migration_with_verified_quote(self):
  with sqlite3.connect(':memory:') as db:
   db.row_factory=sqlite3.Row
   db.execute(sc.REVIEW_DDL)
   old='Protect crucial disability and accessibility survey questions for all households and maintain consistent measures over time. Please keep disability questions.'
   new=old+' Thank you.'
   old_sha=sc.sig('template|'+old);new_sha=sc.sig('template|'+new)
   db.execute('INSERT INTO template_label_review VALUES(?,?,?,?,?,?,?,?,?)',(old_sha,'disability',1,'Please keep disability questions.','AD','reviewed','2026-10-20',old,'X1'))
   units={'u1':{'sha':new_sha,'kind':'template','text':new}}
   self.assertEqual(sc.carry_forward_template_reviews(db,units),1)
   r=db.execute('select * from template_label_review where template_sha=?',(new_sha,)).fetchone()
   self.assertEqual(r['decision'],1)
   self.assertIn('auto-carry',r['reviewer'])
 def test_changed_cluster_reassembles_old_members(self):
  with sqlite3.connect(':memory:') as db:
   db.row_factory=sqlite3.Row
   db.execute('CREATE TABLE comment_clusters(comment_id TEXT, cluster_id TEXT)')
   db.executemany('INSERT INTO comment_clusters VALUES(?,?)',[('a','cl1'),('b','cl1'),('c','cl2')])
   recs=[{'id':i} for i in 'abc'];pending=[recs[0]]
   out=sc.extend_pending_to_affected_clusters(db,recs,pending)
   self.assertEqual({r['id'] for r in out},{'a','b'})
if __name__=='__main__':unittest.main()
