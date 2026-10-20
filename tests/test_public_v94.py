"""V9.4 public-demo route smoke checks: local network only, no API key or GitHub/Railway calls."""
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT=pathlib.Path(__file__).resolve().parents[1]

class PublicDemoQCTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='nhis_public_v94_')
        cls.dbfile=pathlib.Path(cls.temp.name)/'demo.sqlite3'
        with sqlite3.connect(ROOT/'data/comments.sqlite3') as src, sqlite3.connect(cls.dbfile) as dst:
            src.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));cls.port=s.getsockname()[1]
        cls.url=f'http://127.0.0.1:{cls.port}'
        env=os.environ.copy()
        env.update(NHIS_DEPLOYMENT_MODE='hosted',NHIS_PUBLIC_DEMO='1',NHIS_READ_ONLY='1',
                   NHIS_PUBLIC_ORIGIN=cls.url,NHIS_DB_PATH=str(cls.dbfile),PORT=str(cls.port),
                   DEMO_USER='',DEMO_PASSWORD='',OPENAI_API_KEY='')
        cls.proc=subprocess.Popen([sys.executable,'app/server.py','--no-browser'],cwd=ROOT,env=env,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(70):
            if cls.proc.poll() is not None:raise RuntimeError('public demo failed to boot')
            try:
                if cls.get('/healthz')[0]==200:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('public demo timed out')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:cls.proc.kill();cls.proc.wait(timeout=5)
        cls.temp.cleanup()
    @classmethod
    def get(cls,path):
        try:
            with urlopen(cls.url+path,timeout=20) as r:return r.status,r.read(),dict(r.headers)
        except HTTPError as e:return e.code,e.read(),dict(e.headers)
    @classmethod
    def post(cls,path,payload,origin=None):
        req=Request(cls.url+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':origin or cls.url})
        try:
            with urlopen(req,timeout=20) as r:return r.status,r.read()
        except HTTPError as e:return e.code,e.read()
    def test_public_routes_all_load_without_login(self):
        for p in ('/','/app.js','/style.css','/healthz','/api/meta','/api/themes','/api/qc',
                  '/api/local/status','/api/source','/api/comments?q=asthma&page=1&size=20',
                  '/api/comment/CDC-2026-1387-0003',
                  '/api/semantic/status','/api/semantic/download?kind=assignments',
                  '/api/semantic/download?kind=review_queue',
                  '/api/export?kind=all_comments','/api/export?kind=theme_counts','/api/management_brief'):
            status,data,_=self.get(p)
            self.assertEqual(status,200,(p,data[:250]))
            self.assertTrue(data,(p,status))
    def test_facts_and_no_stale_public_display(self):
        meta=json.loads(self.get('/api/meta')[1]);sem=json.loads(self.get('/api/semantic/status')[1]);src=json.loads(self.get('/api/source')[1]);
        self.assertEqual(meta['records'],1693)
        self.assertEqual(sem['coded'],1693)
        self.assertEqual(sem['uncoded_attachment'],0)
        self.assertEqual(sem['attachment_comment_records'],60)
        self.assertEqual(meta['attachment_documents_with_extracted_text'],65)
        self.assertFalse(meta['llm_enabled'])
        self.assertTrue(meta['hosted_readonly'])
        self.assertEqual(src['path'],'Read-only hosted demo')
        self.assertNotIn('C:\\Users',str(src))
        page=self.get('/')[1].decode()
        self.assertNotIn('Password-protected demo',page)
        self.assertNotIn('20 of 65 listed attachment',page)
        js=self.get('/app.js')[1].decode(); css=self.get('/style.css')[1].decode()
        for stale in ('inconsistent classifications','template-consistency QC','Historical AI labels','historical provisional AI labels'):
            self.assertNotIn(stale,page+js,stale)
        self.assertIn('body.hosted .consent-line{display:none!important}',css)
        self.assertIn('Public read-only demo: evidence search only',js)
        self.assertIn('AI-assisted transcription or description of 3 image-only documents',page)
        self.assertNotIn('All 60 attachment-bearing comments are presently awaiting updated AI coding',page)
        appjs=self.get('/app.js')[1].decode()
        self.assertIn('Public · Read-only · No API charges',appjs)
        self.assertIn('Provisional screening label',appjs)
        self.assertNotIn('60 attachment-bearing records await updated classification',appjs)
    def test_readonly_and_evidence_post(self):
        self.assertEqual(self.post('/api/local/query',{'question':'disability questions','model':'','approved':False})[0],200)
        self.assertEqual(self.post('/api/local/query',{'question':'asthma','model':'','approved':False},origin='https://bad.example')[0],400)
        for path in ('/api/override','/api/analyst_review','/api/import','/api/sync','/api/review','/api/export_review','/api/local/compare'):
            self.assertEqual(self.post(path,{'draft':'some draft'})[0],403,path)
        self.assertEqual(self.get('/api/semantic/download?kind=counts')[0],403)

if __name__=='__main__':unittest.main()
