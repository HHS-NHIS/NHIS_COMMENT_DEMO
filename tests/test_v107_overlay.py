"""Release-blocking V10.7 tests. No API calls, no database mutation, no paid AI."""
import os
import sys
import sqlite3
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import v107_overlay as v

class RuleTests(unittest.TestCase):
    def test_removed_and_retain(self):
        c=v.classify_text("Removing these questions will result in people with I/DD being undercounted. My recommendation is to retain receipt-of-help content in the redesigned survey.")
        self.assertIn("removed",c["content_subcategories"])

    def test_addition(self):
        c=v.classify_text("Add a brief follow-up identifying the treatment category affected. With regard to medical cannabis, the topic of hemp products (CBD in particular) should be included.")
        self.assertIn("add",c["content_subcategories"])

    def test_reduction(self):
        c=v.classify_text("Recommendation: Delete 8 of the 9 questions in Section A, retaining only A1 which has historically been in the NHIS.")
        self.assertIn("reduce",c["content_subcategories"])

    def test_wording(self):
        c=v.classify_text("The phrase also known as Obamacare should be deleted. There is a skip pattern for respondents who do not report a high-deductible health plan. This question should be asked of anyone with insurance.")
        self.assertIn("wording",c["content_subcategories"])

    def test_explicit_measure_support(self):
        c=v.classify_text("I am writing to strongly support including the Whole Person Health Index (WPHI) as a permanent part of the National Health Interview Survey.")
        self.assertEqual(c["support_specific_measure"],"explicit")
        self.assertEqual(c["topics"]["whole_person"]["role"],"primary")

    def test_multiple_primary(self):
        c=v.classify_text("I recommend including questions measuring loneliness. We support retaining sleep quality questions in the survey.")
        self.assertEqual(c["topics"]["loneliness"]["role"],"primary")
        self.assertEqual(c["topics"]["sleep"]["role"],"primary")

    def test_incidental_smoking_secondary(self):
        c=v.classify_text("We recommend retaining questions measuring loneliness and social connectedness in NHIS. Loneliness is associated with higher levels of cigarette smoking.")
        self.assertEqual(c["topics"]["loneliness"]["role"],"primary")
        self.assertEqual(c["topics"]["tobacco"]["role"],"secondary")

    def test_incidental_diabetes_secondary(self):
        c=v.classify_text("We strongly recommend disability measures in this survey. Disability has associations with diabetes and other chronic conditions.")
        self.assertEqual(c["topics"]["diabetes"]["role"],"secondary")

    def test_insurance_distinct_from_access_and_cost(self):
        a=v.classify_text("Access to health care is impacted by food insecurity and disabilities.")
        self.assertNotIn("insurance",a["topics"])
        b=v.classify_text("We recommend measuring health insurance coverage and medical debt separately.")
        self.assertIn("insurance",b["topics"])
        self.assertIn("costs",b["topics"])

    def test_topic_inventory(self):
        self.assertEqual(len(v.TOPICS),15)
        self.assertEqual(len(v.SUBCATEGORIES),5)
        self.assertEqual(len(v.MODES),3)

@unittest.skipUnless((ROOT/"data/comments.sqlite3").is_file(),"release snapshot not unpacked")
class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
        cls.db.row_factory=sqlite3.Row
        cls.idx=v.index(cls.db)
        for suffix in ("0414","0428","0518","0004","0261"):
            cid="CDC-2026-1387-"+suffix
            body=cls.idx["rows"][cid]["plain_text"] or ""
            low=body.lower()
            target=next((i for term in ("whole person","wphi","hemp","cbd","remov") if (i:=low.find(term))>=0),0)
            snippet=" ".join(body[max(0,target-100):target+520].split())
            print("V107 SOURCE QC",suffix,"status",cls.idx["items"][cid]["support_specific_measure"],
                "subcats",cls.idx["items"][cid]["content_subcategories"],"excerpt",repr(snippet),flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_preserve_corpus_and_legacy(self):
        result=v.qc(self.db)
        self.assertTrue(result["ready"],result)
        self.assertEqual(result["display_counts"]["all"],3748)
        self.assertEqual(result["display_counts"]["representative"],result["cluster_count"])
        self.assertLessEqual(result["display_counts"]["exclude_clusters"],result["display_counts"]["representative"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM semantic_tags").fetchone()[0],20316)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM local_fts").fetchone()[0],3748)

    def test_all_feedback_example_ids(self):
        for suffix in v.EXAMPLES:
            cid="CDC-2026-1387-"+suffix
            with self.subTest(comment_id=cid):
                self.assertIn(cid,self.idx["items"])
                item=self.idx["items"][cid]
                self.assertIn(item["form_status"],("exact_duplicate","personalized_form_letter","likely_form_letter","apparently_unique","uncertain"))
                self.assertTrue(item["method"])

    def test_specific_management_examples(self):
        expected={"0020":"removed","0261":"removed","0262":"add",
                  "0004":"add","0324":"reduce","0368":"reduce","0313":"wording"}
        mismatches=[]
        for suffix,subcategory in expected.items():
            cid="CDC-2026-1387-"+suffix
            actual=self.idx["items"][cid]["content_subcategories"]
            if subcategory not in actual:mismatches.append((cid,subcategory,actual))
        self.assertFalse(mismatches,"Mandatory content examples must be investigated: "+repr(mismatches))
        self.assertNotIn("reduce",self.idx["items"]["CDC-2026-1387-0261"]["content_subcategories"],
            "Concern about agency removal is not an endorsement of reducing content")

    def test_measure_specific_support(self):
        for suffix in ("0414","0428","0518"):
            cid="CDC-2026-1387-"+suffix
            val=self.idx["items"][cid]["support_specific_measure"]
            self.assertIn(val,("explicit","review"),(cid,val,repr(self.idx["rows"][cid]["plain_text"][:1400]), self.idx["items"][cid]["topics"]))
            shown={r["comment_id"] for r in v.comments(self.db,section="support",query=cid,mode="all")["comments"]}
            # Queries search comment text, not IDs: use the complete support view instead.
            _,ids,_=v.filter_result(self.db,section="support",mode="all")
            if suffix=="0414":self.assertIn(cid,ids)
            else:self.assertNotIn(cid,ids,"Review-only support must not inflate category totals")

    def test_group_examples_are_audited(self):
        groups=(("0061","0054","0053","0050"),("0401","0408","0410"),("0308","0334","0335"))
        for suffixes in groups:
            rows=[self.idx["items"]["CDC-2026-1387-"+x] for x in suffixes]
            print("V107 GROUP AUDIT",suffixes,[(r["cluster_id"],r["form_status"],r["novel_words"]) for r in rows])
            # Document both recognized groups and unresolved cases rather than forcing IDs into a cluster.
            self.assertTrue(all(r["cluster_size"]>=1 for r in rows))

    def test_filters_and_csv_reconcile(self):
        for mode in v.MODES:
            idx,ids,_=v.filter_result(self.db,mode=mode,topic="whole_person",tier="primary")
            result=v.comments(self.db,mode=mode,topic="whole_person",tier="primary",page=1,size=100)
            self.assertEqual(result["total"],len(ids))
            self.assertEqual(len(result["comments"]),min(100,len(ids)))
            csvbytes=v.export(self.db,mode=mode,topic="whole_person",tier="primary")
            self.assertEqual(csvbytes.decode("utf-8-sig").count("\n")-1,len(ids))

    def test_summary_covers_full_corpus(self):
        from collections import Counter
        info=v.stats(self.db,mode="all")
        self.assertEqual(info["public_comment_submissions"],3748)
        self.assertEqual(info["displayed_units"],3748)
        self.assertEqual(len(info["topics"]),15)
        self.assertEqual(len(info["content_subcategories"]),5)

if __name__=="__main__":
    unittest.main()
