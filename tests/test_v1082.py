"""V10.8.2 release gates: focus-based primary topics, generic cluster links and metadata."""
import csv,io,sqlite3,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import v107_overlay as f

class FocusUnitTests(unittest.TestCase):
 def test_valuable_measure_is_primary(self):
  x=f.classify_text("I use the Whole Person Health Index as a valuable measure. This index is a useful tool for studying student wellbeing.")
  self.assertEqual(x["topics"]["whole_person"]["role"],"primary")
 def test_inclusion_praised_first_is_primary(self):
  x=f.classify_text("The inclusion of the Whole Person Health Index questions as part of the permanent NHIS Study is crucial. Better data will help communities.")
  self.assertEqual(x["topics"]["whole_person"]["role"],"primary")
 def test_incidental_quality_of_life_is_secondary(self):
  x=f.classify_text("I research disability, health, and quality of life. I recommend NHIS retain disability questions.")
  self.assertEqual(x["topics"]["whole_person"]["role"],"secondary")
 def test_incidental_smoking_is_secondary(self):
  x=f.classify_text("Please retain loneliness questions in the survey. Loneliness can be linked to cigarette smoking.")
  self.assertEqual(x["topics"]["tobacco"]["role"],"secondary")
 def test_version_metadata(self):
  version=(ROOT/"VERSION.txt").read_text()
  self.assertIn("V10.8.2",version)
  self.assertIn("3,748",version)
  self.assertNotIn("1,693",version)
  self.assertNotIn("V9.6",version)

@unittest.skipUnless((ROOT/"data/comments.sqlite3").is_file(),"Frozen public data required")
class CorpusTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
  cls.db.row_factory=sqlite3.Row
  cls.idx=f.index(cls.db)
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def test_named_wphi_letters_primary_but_review_support(self):
  for code in ("0428","0518"):
   cid="CDC-2026-1387-"+code
   self.assertEqual(self.idx["items"][cid]["topics"]["whole_person"]["role"],"primary")
   self.assertEqual(self.idx["items"][cid]["support_specific_measure"],"review")
   self.assertIn(cid,f.filter_result(self.db,section="summary",topic="whole_person",tier="primary")[1])
 def test_support_review_visible_with_primary_filter(self):
  d=f.stats(self.db,section="support",topic="whole_person",tier="primary",mode="all")
  for code in ("0428","0518"):self.assertIn("CDC-2026-1387-"+code,d["support_review"]["example_ids"])
 def test_primary_insurance_and_incidental_medication(self):
  idx=self.idx["items"]
  self.assertEqual(idx["CDC-2026-1387-0295"]["topics"]["insurance"]["role"],"primary")
  self.assertEqual(idx["CDC-2026-1387-0324"]["topics"]["medications"]["role"],"secondary")
 def test_generic_links_and_audit_export(self):
  idx=self.idx
  self.assertEqual(idx["cluster_count"],882)
  self.assertEqual(len(idx["cross_cluster_edges"]),6)
  linked=["CDC-2026-1387-"+x for x in ("0308","0334","0335")]
  self.assertEqual(len({idx["items"][cid]["cluster_id"] for cid in linked}),1)
  self.assertTrue(all(idx["items"][cid]["cross_cluster_review"] for cid in linked))
  csvrows=list(csv.DictReader(io.StringIO(f.export(self.db,mode="representative",topic="whole_person",tier="primary").decode("utf-8-sig"))))
  self.assertIn("original_cluster_id",csvrows[0])
  self.assertIn("cross_cluster_review",csvrows[0])
  self.assertEqual(len(csvrows),f.comments(self.db,mode="representative",topic="whole_person",tier="primary")["total"])
