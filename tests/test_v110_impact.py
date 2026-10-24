"""V10.10 release acceptance: separate, source-verified prioritization ledger."""
import unittest,os,re,json,sqlite3,unicodedata,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"app/impact-issues.html"
def load():
    h=SOURCE.read_text(encoding="utf-8")
    issues=json.loads(re.search(r'<script id="data-issues" type="application/json">([\s\S]*?)</script>',h).group(1))
    recs=json.loads(re.search(r'<script id="data-recs" type="application/json">([\s\S]*?)</script>',h).group(1))
    return h,issues,recs
def norm(s):
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",str(s or "")).replace("‘","'").replace("’","'").replace("“",'"').replace("”",'"').replace("\u00ad","")).casefold().strip()

class LedgerIntegrity(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.html,cls.issues,cls.recs=load()
 def test_dataset_and_issue_counts(self):
    self.assertEqual(len(self.issues),201)
    self.assertEqual(len(self.recs),1464)
    self.assertEqual(len({r["comment_id"] for r in self.recs}),815)
    self.assertEqual(len({i["issue_id"] for i in self.issues}),201)
 def test_issue_scoring_and_recommendation_links(self):
    linked=collections.Counter(r["issue_id"] for r in self.recs)
    for i in self.issues:
        self.assertEqual(i["total"],sum(i[k] for k in ("specificity","evidence","consequence","feasibility","novelty")))
        self.assertEqual(i["must_review"],"Yes" if i["specificity"]>=4 or i["evidence"]>=4 else "No")
        self.assertEqual(i["n_recs"],linked[i["issue_id"]])
        self.assertEqual(i["unique_comments"],len({r["comment_id"] for r in self.recs if r["issue_id"]==i["issue_id"]}))
    self.assertEqual(sum(i["must_review"]=="Yes" for i in self.issues),142)
 def test_original_data_is_source_derived_and_provisional(self):
    self.assertIn("AI-assisted extraction and scoring",self.html)
    self.assertIn("Not human-validated",self.html)
    script=self.html.rsplit("<script>",1)[-1].split("</script>",1)[0]
    for prohibited in ("fetch(","XMLHttpRequest","navigator.sendBeacon","document.cookie","localStorage","postMessage","window.parent"):
        self.assertNotIn(prohibited,script)
 def test_ui_and_server_sandbox(self):
    host=(ROOT/"app/index.html").read_text()
    server=(ROOT/"app/server.py").read_text()
    app=(ROOT/"app/app.js").read_text()
    self.assertIn('data-tab="impact"',host)
    self.assertIn('id="tab-impact"',host)
    self.assertIn('sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"',host)
    self.assertIn('src="/impact-issues.html"',host)
    self.assertIn("201 identified issues",host)
    self.assertIn("frame-ancestors 'self'",server)
    self.assertIn("connect-src 'none'",server)
    self.assertIn("embedded=True",server)
    self.assertIn("impact:['ISSUE PRIORITIZATION'",app)

@unittest.skipUnless((ROOT/"data/comments.sqlite3").exists(),"requires unpacked frozen corpus")
class QuoteProvenance(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    _,cls.issues,cls.recs=load()
    cls.db=sqlite3.connect("file:"+str((ROOT/"data/comments.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True)
    cls.db.row_factory=sqlite3.Row
 @classmethod
 def tearDownClass(cls):
    cls.db.close()
 def test_all_quotes_and_links_against_frozen_corpus(self):
    comments={r["comment_id"]:(r["plain_text"],r["comment_url"]) for r in self.db.execute("SELECT comment_id,plain_text,comment_url FROM comments")}
    at=collections.defaultdict(list)
    for r in self.db.execute("SELECT comment_id,text FROM attachment_text"):at[r["comment_id"]].append(norm(r["text"]))
    self.assertEqual(len(comments),3748)
    matched_body=matched_attachment=0
    for r in self.recs:
        self.assertIn(r["comment_id"],comments)
        body,url=comments[r["comment_id"]]
        self.assertEqual(r["url"],url)
        quote=norm(r["quote"])
        if quote in norm(body): matched_body+=1
        else:
            self.assertTrue(any(quote in t for t in at[r["comment_id"]]),r["rec_id"]+" quote mismatch")
            matched_attachment+=1
    self.assertEqual((matched_body,matched_attachment),(942,522))
    for i in self.issues:
        for cid in i["supporting_ids"]:self.assertIn(cid,comments)
if __name__=="__main__":unittest.main()
