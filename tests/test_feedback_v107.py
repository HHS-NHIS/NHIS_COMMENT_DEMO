"""Regression checks for additive feedback facets; no network or paid AI."""
import csv
import io
import sqlite3
import unittest
from app import feedback_addon as f

class FeedbackFacetTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript("""
        CREATE TABLE comments(comment_id TEXT PRIMARY KEY, normalized_sha TEXT, plain_text TEXT, title TEXT, comment_url TEXT);
        CREATE TABLE comment_clusters(comment_id TEXT PRIMARY KEY, cluster_id TEXT,cluster_size INTEGER,overlap REAL,personalized INTEGER);
        CREATE TABLE attachment_text(comment_id TEXT,text TEXT,status TEXT);
        """)
        rows=[
          ('001','same','Please retain whole person health (WPHI). I strongly support including WPHI.','WPHI','https://www.regulations.gov/comment/test-001','001',3,1,0),
          ('002','same','Please retain whole person health (WPHI). I strongly support including WPHI.','WPHI','https://www.regulations.gov/comment/test-002','001',3,1,0),
          ('003','variation','Please retain whole person health (WPHI). I strongly support including WPHI. My own experiences are important.','WPHI','https://www.regulations.gov/comment/test-003','001',3,.8,1),
          ('004','different','This disability issue is associated with cigarette smoking.','Other','https://www.regulations.gov/comment/test-004','004',1,1,0),
        ]
        for cid,sha,body,title,url,cl,n,ov,personal in rows:
            self.db.execute('INSERT INTO comments VALUES (?,?,?,?,?)',(cid,sha,body,title,url))
            self.db.execute('INSERT INTO comment_clusters VALUES (?,?,?,?,?)',(cid,cl,n,ov,personal))
        self.db.commit()
        self.idx=f.build_index(self.db)
    def tearDown(self):self.db.close()
    def test_form_status_and_modes(self):
        self.assertEqual(self.idx['flags']['001']['status'],'exact_repeated_text')
        self.assertEqual(self.idx['flags']['003']['status'],'likely_form_letter')
        self.assertEqual(self.idx['flags']['004']['status'],'not_flagged')
        ids=set(self.idx['flags'])
        self.assertEqual(len(f.select_ids(self.idx,ids,'all')),4)
        self.assertEqual(len(f.select_ids(self.idx,ids,'representative')),2)
        self.assertEqual(f.select_ids(self.idx,ids,'exclude'),{'004'})
    def test_representative_is_within_filtered_set(self):
        self.assertEqual(f.select_ids(self.idx,{'003','004'},'representative'),{'003','004'})
    def test_explicit_measure_support_and_multiple_topics(self):
        self.assertIn('001',self.idx['measure_support'])
        self.assertEqual(self.idx['topics']['001']['wphi']['relevance'],'primary')
        self.assertEqual(self.idx['topics']['004']['tobacco']['relevance'],'incidental')
    def test_wphi_phrase_variations(self):
        for phrase in [
           'I strongly support including the Whole Person Health Index as a permanent measure.',
           'I would love to see WPHI integrated into NHIS.',
           'The inclusion of WPHI questions as a permanent measure is crucial.']:
            self.assertTrue(f.measure_support(phrase),phrase)
    def test_summary_invariant_and_errors(self):
        x=f.summary(self.idx,self.idx['flags'],mode='exclude')
        self.assertEqual(x['total_submissions'],4)
        self.assertEqual(x['matching_records'],1)
        self.assertEqual(x['exact_repeated_text']+x['likely_form_letter']+x['not_flagged'],4)
        self.assertIn('top_primary_topics',x)
        with self.assertRaises(ValueError):f.select_ids(self.idx,[],mode='unknown')
    def test_csv_scope_and_no_writes(self):
        before=self.db.total_changes
        data=f.filtered_csv(self.db,self.idx,{'001'},'all','wphi','primary','','support')
        rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual({r['comment_id'] for r in rows},{'001'})
        self.assertEqual(rows[0]['selected_management_view'],'support')
        self.assertEqual(rows[0]['supports_specific_measure'],'1')
        self.assertEqual(self.db.total_changes,before)
if __name__=='__main__':unittest.main()
