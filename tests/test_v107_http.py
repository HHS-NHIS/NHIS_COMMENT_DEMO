"""V10.7 HTTP regression smoke: production Handler, frozen dataset, no external network/AI."""
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import server as s

class FullDashboardHTTPT(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv=s.ThreadingHTTPServer(("127.0.0.1",0),s.Handler)
        cls.url="http://127.0.0.1:"+str(cls.srv.server_address[1])
        cls.thread=threading.Thread(target=cls.srv.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown();cls.srv.server_close();cls.thread.join(timeout=3)
    @classmethod
    def get(cls,path):
        with urlopen(cls.url+path,timeout=30) as response:
            return response.status,response.read(),response.headers
    def test_original_full_tabs_and_new_tab(self):
        code,raw,headers=self.get("/")
        self.assertEqual(code,200)
        html=raw.decode()
        for tab in ("overview","local-ai","semantic","query","themes","explorer",
                    "review","qc","imports","management","feedback"):
            self.assertIn('id="tab-'+tab+'"',html)
        self.assertIn("v107Mode",html)
        self.assertIn("v107Topic",html)
        self.assertEqual(headers["X-Frame-Options"],"DENY")
        for path in ("/app.js","/v107.js","/style.css"):
            status,raw,_=self.get(path)
            self.assertEqual(status,200)
            self.assertGreater(len(raw),1000)

    def test_existing_endpoints(self):
        for url in ("/healthz","/api/meta","/api/qc","/api/themes",
            "/api/source","/api/local/status","/api/semantic/status",
            "/api/management","/api/management/comments?section=content&page=1",
            "/api/comments?page=1&size=5","/api/comment/CDC-2026-1387-0414",
            "/api/export?kind=query_matches&q=asthma","/api/management/export?section=content",
            "/api/management/coded-export","/api/management/topic-export",
            "/api/management/topic-report","/api/management/report",
            "/api/management_brief"):
            with self.subTest(url=url):
                st,data,headers=self.get(url)
                self.assertEqual(st,200)
                self.assertTrue(data)
        meta=json.loads(self.get("/api/meta")[1])
        self.assertEqual(meta["records"],3748)
        self.assertTrue(meta["hosted_readonly"])
        management=json.loads(self.get("/api/management")[1])
        self.assertTrue(management["ready"])
        self.assertEqual(len(management["sections"]),8)
        self.assertEqual(len(management["topic_combinations"]),240)

    def test_new_endpoints_mode_and_export_consistency(self):
        qc=json.loads(self.get("/api/v107/qc")[1])
        self.assertTrue(qc["ready"],qc)
        self.assertEqual(qc["display_counts"]["all"],3748)
        for mode in ("all","representative","exclude_clusters"):
            with self.subTest(mode=mode):
                params="?form_mode="+mode+"&v107_topic=whole_person&v107_tier=primary"
                stats=json.loads(self.get("/api/v107/stats"+params)[1])
                filtered=json.loads(self.get("/api/v107/comments"+params+"&size=10")[1])
                mg=json.loads(self.get("/api/management/comments?section=summary&"+params[1:]+"&size=10")[1])
                self.assertEqual(stats["displayed_units"],filtered["total"])
                self.assertEqual(mg["total"],filtered["total"])
                csv=self.get("/api/v107/export"+params)[1].decode("utf-8-sig")
                self.assertEqual(csv.count("\n")-1,filtered["total"])
                self.assertIn("management_categories",csv.splitlines()[0])
                self.assertEqual(json.loads(self.get("/api/comments"+params+"&size=10")[1])["total"],filtered["total"])

    def test_support_examples_in_filtered_management_export(self):
        csv=self.get("/api/management/export?section=support&form_mode=all&v107_topic=whole_person")[1].decode("utf-8-sig")
        for code in ("0414","0428","0518"):
            self.assertIn("CDC-2026-1387-"+code,csv)

    def test_old_and_new_source_detail_and_provisional_labels(self):
        data=json.loads(self.get("/api/comment/CDC-2026-1387-0414")[1])
        self.assertIn("themes",data)
        self.assertIn("cluster",data)
        self.assertIn("v107",data)
        self.assertEqual(data["v107"]["support_specific_measure"],"explicit")

    def test_security_read_only_paid_off_and_origin_guard(self):
        url=self.url+"/api/override"
        req=Request(url,data=b'{"comment_id":"CDC-2026-1387-0414","theme_id":"sleep","decision":1}',
                    headers={"Content-Type":"application/json","Origin":self.url},method="POST")
        with self.assertRaises(HTTPError) as cm:urlopen(req,timeout=8)
        self.assertEqual(cm.exception.code,403)
        self.assertNotIn("OPENAI_API_KEY",json.dumps(json.loads(self.get("/api/meta")[1])))
        req=Request(self.url+"/api/local/query",
                    data=b'{"question":"hi","approved":true,"model":"gpt-4.1-mini"}',
                    headers={"Content-Type":"application/json","Origin":self.url},method="POST")
        with self.assertRaises(HTTPError) as cm:urlopen(req,timeout=8)
        self.assertEqual(cm.exception.code,400)

if __name__=="__main__":
    unittest.main()
