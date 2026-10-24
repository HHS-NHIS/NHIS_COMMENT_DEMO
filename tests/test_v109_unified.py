"""V10.9 integrated management analysis: source cohort, facets, form flags, exports."""
import csv,io,sqlite3,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import v107_overlay as f

class BrowserContractTests(unittest.TestCase):
 def test_single_combined_navigation(self):
  h=(ROOT/"app/index.html").read_text()
  self.assertIn('src="/v109_management.js"',h)
  self.assertNotIn('src="/v108_management.js"',h)
  self.assertIn('class="nav hide" data-tab="feedback"',h)
  self.assertIn('id="mgTheme"',h)
  self.assertIn('id="mgTopic"',h)
  self.assertIn('id="mgTopicCompare"',h)
  self.assertIn('id="mgFormFlag"',h)
  self.assertNotIn('V10.6',h)
  j=(ROOT/"app/v109_management.js").read_text()
  for k in ('Full-Corpus Management Synthesis','mgFormAudit','mgAuditMode',
            'topic_intersection','mgDownloadCSV','mgFormFlag','v107Render'):
   self.assertIn(k,j)
  self.assertIn("All management categories (Summary)",j)
 def test_responsive_topic_labels(self):
  css=(ROOT/"app/style.css").read_text()
  self.assertNotIn('grid-template-columns:45px',css)
  self.assertIn('minmax(155px,1fr)',css)
  self.assertIn('overflow-wrap:break-word',css)
 def test_static_script_allowed(self):
  server=(ROOT/"app/server.py").read_text()
  self.assertIn("'/v109_management.js'",server)
  self.assertIn("v109_form_flag",server)
  self.assertIn("v109_topic_compare",server)

@unittest.skipUnless((ROOT/"data/comments.sqlite3").is_file(),"unpacked frozen corpus required")
class IntegratedDataTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
  cls.db.row_factory=sqlite3.Row
  cls.idx=f.index(cls.db)
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def test_form_letter_flag_partitions_all_3748_records(self):
  a=len(f.filter_result(self.db,section="summary",form_flag="identified")[1])
  b=len(f.filter_result(self.db,section="summary",form_flag="not_identified")[1])
  all_count=len(f.filter_result(self.db,section="summary")[1])
  self.assertEqual((a,b,all_count),(2911,837,3748))
  self.assertEqual(len(f.filter_result(self.db,mode="representative")[1]),882)
 def test_two_topic_AND_and_jaccard(self):
  a="insurance";b="whole_person"
  ids=f.filter_result(self.db,section="summary",topic=a,topic2=b,mode="all")[1]
  d=f.stats(self.db,section="summary",topic=a,topic2=b,mode="all")
  pair=d["topic_intersection"]
  self.assertEqual(pair["both"],len(ids))
  self.assertEqual(pair["both"],39)
  self.assertEqual(pair["a_count"],len(f.filter_result(self.db,section="summary",topic=a)[1]))
  self.assertEqual(pair["b_count"],len(f.filter_result(self.db,section="summary",topic=b)[1]))
  self.assertAlmostEqual(pair["jaccard"],round(100*len(ids)/(pair["a_count"]+pair["b_count"]-len(ids)),1))
 def test_relevant_original_and_additional_facet(self):
  options=f.management_filter_options(self.db,section="summary",topic="insurance")
  self.assertTrue(options["original_themes"])
  self.assertTrue(any(x["id"]=="whole_person" for x in options["comparison_topics"]))
  self.assertFalse(any(x["id"]=="insurance" for x in options["comparison_topics"]))
  self.assertTrue(all(x["count"]>0 for x in options["additional_topics"]))
  old=options["original_themes"][0]["id"]
  c=f.filter_result(self.db,section="summary",legacy_theme=old,topic="insurance")[1]
  self.assertLessEqual(len(c),len(f.filter_result(self.db,section="summary",topic="insurance")[1]))
 def test_content_and_form_letter_intersect(self):
  q=dict(section="content",subcategory="removed",topic="loneliness",form_flag="not_identified")
  d=f.stats(self.db,**q)
  result=f.comments(self.db,**q)
  reader=list(csv.DictReader(io.StringIO(f.export(self.db,**q).decode("utf-8-sig"))))
  self.assertEqual(d["displayed_units"],result["total"])
  self.assertEqual(len(reader),result["total"])
  self.assertTrue(all(self.idx["items"][r["comment_id"]]["cluster_size"]==1 for r in reader))
 def test_reviewer_examples_and_generic_clusters_preserved(self):
  for code in ("0428","0518"):
   cid="CDC-2026-1387-"+code
   self.assertEqual(self.idx["items"][cid]["topics"]["whole_person"]["role"],"primary")
  self.assertEqual(len(self.idx["cross_cluster_edges"]),6)
  self.assertIn("CDC-2026-1387-0414",
       f.filter_result(self.db,section="support",topic="whole_person")[1])
 def test_original_reports_unmodified(self):
  from management_addon import load
  state=load(self.db)
  self.assertTrue(state["ready"])
  self.assertEqual(state["corpus_records"],3748)
if __name__=="__main__":unittest.main()
