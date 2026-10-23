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


class ContextRuleTests(unittest.TestCase):
 def test_no_weak_support_promoted(self):
  v=f.classify_text("These questions are very important to retain in the NHIS, but I oppose the redesign.")
  self.assertNotEqual(v["support_specific_measure"],"explicit")
 def test_explicit_support(self):
  v=f.classify_text("We strongly support including the Whole Person Health Index as a permanent NHIS measure.")
  self.assertEqual(v["support_specific_measure"],"explicit")
 def test_no_nonpharmaceutical_medication_tag(self):
  x=f.classify_text("We recommend measuring non-pharmaceutical mental health management.")
  self.assertNotIn("medications",x["topics"])
 def test_explicit_omission_from_proposed_survey(self):
  x=f.classify_text("Existing NHIS assistance measures are not carried forward in the proposed 2028 questionnaire. My recommendation is to retain them.")
  self.assertIn("removed",x["content_subcategories"])
 def test_keep_without_removal_context(self):
  x=f.classify_text("These questions are important and should continue in the survey.")
  self.assertNotIn("removed",x["content_subcategories"])
 def test_incidental_topic_not_primary(self):
  x=f.classify_text("We recommend questions measuring loneliness. Loneliness is associated with higher cigarette smoking.")
  self.assertEqual(x["topics"]["loneliness"]["role"],"primary")
  self.assertEqual(x["topics"]["tobacco"]["role"],"secondary")

@unittest.skipUnless((ROOT/"data/comments.sqlite3").is_file(),"requires unpacked release data")
class AdditionalCorpusTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
  cls.db.row_factory=sqlite3.Row
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def test_phrase_search_not_broad_any(self):
  phrase=f.filter_result(self.db,section="summary",query="whole person health",match="phrase")[1]
  any_words=f.filter_result(self.db,section="summary",query="whole person health",match="any")[1]
  self.assertTrue(0<len(phrase)<len(any_words))
  self.assertLess(len(phrase),150)
 def test_attachment_only_phrase_matches(self):
  matches=set(f.filter_result(self.db,section="summary",query="whole person health",match="phrase")[1])
  for code in ("0025","0368","0854","1868","1893","1902"):
   self.assertIn("CDC-2026-1387-"+code,matches)
 def test_review_does_not_inflate_support(self):
  allsupport=set(f.filter_result(self.db,section="support",mode="all")[1])
  for code in ("0428","0518"):
   self.assertNotIn("CDC-2026-1387-"+code,allsupport)
  self.assertIn("CDC-2026-1387-0414",allsupport)
  self.assertLess(len(allsupport),110,"Weak support rule has inflated the category")
  print("QC_REVIEW_COUNTS support="+str(len(allsupport))+" removed="+str(len(f.filter_result(self.db,section="content",subcategory="removed")[1]))+" med_primary="+str(f.stats(self.db,mode="all")["topics"][[x["id"] for x in f.stats(self.db,mode="all")["topics"]].index("medications")]["primary"]),flush=True)
 def test_linked_near_duplicates(self):
  idx=f.index(self.db)
  codes=["CDC-2026-1387-"+k for k in ("0308","0334","0335")]
  self.assertEqual(len({idx["items"][i]["cluster_id"] for i in codes}),1)
  self.assertEqual(f.qc(self.db)["display_counts"]["representative"],886)
 def test_false_medications_major_cluster(self):
  item=f.index(self.db)["items"]["CDC-2026-1387-0324"]
  self.assertNotIn("medications",[k for k,v in item["topics"].items() if v["role"]=="primary"])

