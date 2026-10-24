"""V10.10.1 release documentation, offline fonts and mobile layout contracts."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return (ROOT/p).read_text(encoding="utf-8")
class UpdatedReleaseQCTests(unittest.TestCase):
 def test_current_readme(self):
    s=read("README.md")
    for val in ("3,748 publicly posted/indexed","45","2,911","837","882","48","2,908","python scripts/run_release_qc.py"):
        self.assertIn(val,s)
    self.assertNotIn("snapshot of 1,693 comments",s)
 def test_qc_replaced(self):
    s=read("DEMO_READINESS_QC.md")
    self.assertIn("V10.10.1",s)
    self.assertIn("201 issues",s)
    self.assertIn("1,464 recommendations",s)
    self.assertNotIn("V9.6 public-demo QC",s)
 def test_ledger_self_contained(self):
    ledger=read("app/impact-issues.html")
    self.assertIn("3,748 publicly posted/indexed",ledger)
    self.assertIn("October 21, 2026 inventory",ledger)
    self.assertNotIn("comments through Oct 20",ledger)
    self.assertNotIn("fonts.googleapis.com",ledger)
    self.assertNotIn("fonts.gstatic.com",ledger)
    self.assertNotIn("(Safranek)",ledger)
    server=read("app/server.py")
    self.assertNotIn("fonts.googleapis.com",server)
    self.assertNotIn("fonts.gstatic.com",server)
 def test_mobile_and_version_title(self):
    self.assertIn("V10.10.1</title>",read("app/index.html"))
    css=read("app/style.css")
    for needle in ("#tab-management .actions .button","overflow-wrap:anywhere","white-space:normal","grid-template-columns:minmax(0,1fr)"):
        self.assertIn(needle,css)
 def test_test_runner(self):
    s=read("scripts/run_release_qc.py")
    self.assertIn("unpack_payload.py",s)
    self.assertIn("verify_public_release.py",s)
    self.assertIn("test_v111_*.py",s)
if __name__=="__main__":unittest.main()
