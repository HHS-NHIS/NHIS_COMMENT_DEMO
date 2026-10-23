"""Release gate: integrated relevant facets, filter/count/export consistency."""
import sys,csv,io,sqlite3,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import v107_overlay as f
class UITests(unittest.TestCase):
 def test_controls_and_historical_label(self):
  html=(ROOT/"app/index.html").read_text()
  js=(ROOT/"app/v108_management.js").read_text()
  self.assertIn('class="panel hide" id="v107GlobalPanel"',html)
  for name in ("mgSection","mgTheme","mgContent","mgTier","mgFormMode","mgQuery","mgReset"):
   self.assertIn('id="'+name+'"',html)
  self.assertIn("All submissions",html)
  self.assertIn("All recommendation types",html)
  self.assertIn("All topics / measures",js)
  self.assertIn("Original V10.6 syntheses",js)
  self.assertIn("All management categories (Summary)",js)
@unittest.skipUnless((ROOT/"data/comments.sqlite3").is_file(),"requires unpacked release data")
class CorpusTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
  cls.db.row_factory=sqlite3.Row
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def test_only_relevant_values(self):
  for section in ("content","support","criticism","summary"):
   with self.subTest(section=section):
    o=f.management_filter_options(self.db,section=section)
    self.assertTrue(o["topics"])
    self.assertTrue(all(x["count"]>0 for x in o["topics"]))
    self.assertEqual(bool(o["recommendation_types"]),section=="content")
 def test_exact_filtered_counts_and_csv(self):
  for q in (dict(section="content",subcategory="removed",mode="all"),
            dict(section="content",subcategory="reduce",mode="representative"),
            dict(section="support",topic="whole_person",tier="primary",mode="all"),
            dict(section="summary",topic="sleep",tier="secondary",mode="exclude_clusters")):
   with self.subTest(q=q):
    s=f.stats(self.db,**q)
    c=f.comments(self.db,**q)
    rows=list(csv.DictReader(io.StringIO(f.export(self.db,**q).decode("utf-8-sig"))))
    self.assertEqual(s["displayed_units"],c["total"])
    self.assertEqual(c["total"],len(rows))
 def test_content_feedback_examples(self):
  ids=f.filter_result(self.db,section="content",subcategory="removed")[1]
  self.assertIn("CDC-2026-1387-0261",ids)
 def test_role_facets(self):
  o=f.management_filter_options(self.db,section="support",topic="whole_person")
  self.assertTrue(any(x["kind"]=="additional" and x["id"]=="whole_person" for x in o["topics"]))
  self.assertTrue(o["topic_roles"])
if __name__=="__main__":unittest.main()
