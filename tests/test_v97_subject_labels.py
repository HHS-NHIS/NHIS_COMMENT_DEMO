"""Non-regression checks: subject labels are explanatory; they do not reclassify records."""
import csv
import io
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from core import template_groups, export_report, cluster_subjects, analysis_qc

class FormLetterSubjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect((ROOT/'data'/'comments.sqlite3').as_uri()+'?mode=ro',uri=True)
        cls.db.row_factory=sqlite3.Row
        cls.groups=template_groups(cls.db)

    @classmethod
    def tearDownClass(cls):cls.db.close()

    def test_catalog_covers_all_present_form_letter_clusters(self):
        expected=json.loads((ROOT/'form_letter_subjects.json').read_text())['labels']
        self.assertEqual(len(expected),29)
        self.assertEqual(len(self.groups),29)
        self.assertEqual(sum(g['size'] for g in self.groups),1333)
        self.assertEqual([g['size'] for g in self.groups[:2]],[993,236])
        self.assertTrue(all(g['subject_source_id'] and g['subject']!='Subject not yet reviewed' for g in self.groups))

    def test_descriptions_and_provenance_are_not_theme_guesses(self):
        for g in self.groups:
            self.assertGreater(len(g['subject']),12)
            self.assertGreater(len(g['subject_summary']),25)
            self.assertIn('Provisional',g['subject_status'])
            member=self.db.execute('SELECT cluster_id FROM comment_clusters WHERE comment_id=?',(g['subject_source_id'],)).fetchone()
            self.assertEqual(member[0],g['cluster_id'])

    def test_qc_view_lists_all_29_groups(self):
        qc=analysis_qc(self.db)
        self.assertEqual(len(qc['shared_opening_groups']),29)
        self.assertEqual(qc['shared_opening_groups'][0]['subject'],self.groups[0]['subject'])

    def test_summary_export_subjects_and_counts(self):
        rows=list(csv.DictReader(io.StringIO(export_report(self.db,'template_groups').lstrip('\ufeff'))))
        self.assertEqual(len(rows),29)
        self.assertEqual(sum(int(x['size']) for x in rows),1333)
        self.assertEqual(rows[0]['subject'],self.groups[0]['subject'])
        self.assertIn('subject_summary',rows[0])
        self.assertIn('subject_source_id',rows[0])

    def test_member_export_carries_subject_and_keeps_singletons(self):
        rows=list(csv.DictReader(io.StringIO(export_report(self.db,'clusters').lstrip('\ufeff'))))
        self.assertEqual(len(rows),1693)
        members=[r for r in rows if int(r['cluster_size'])>1]
        unique=[r for r in rows if int(r['cluster_size'])==1]
        self.assertEqual(len(members),1333)
        self.assertEqual(len(unique),360)
        self.assertEqual({r['subject'] for r in rows if r['cluster_id']=='CDC-2026-1387-0042'},
            {'Retain disability questions and health-policy data'})
        self.assertTrue(all(r['subject']=='Not a form-letter group' for r in unique))

    def test_label_overlay_does_not_change_db(self):
        a=self.db.execute('SELECT COUNT(*) FROM semantic_tags').fetchone()[0]
        b=self.db.execute('SELECT COUNT(*) FROM comment_clusters').fetchone()[0]
        template_groups(self.db);cluster_subjects(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM semantic_tags').fetchone()[0],a)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM comment_clusters').fetchone()[0],b)

    def test_public_ui_and_docker_copy_catalog(self):
        js=(ROOT/'app'/'app.js').read_text()
        html=(ROOT/'app'/'index.html').read_text()
        docker=(ROOT/'Dockerfile').read_text()
        self.assertIn("esc(g.subject",js)
        self.assertIn("esc(g.subject_summary",js)
        self.assertIn("cl.subject",js)
        self.assertIn('subjects and requests',html)
        self.assertIn('COPY form_letter_subjects.json',docker)

if __name__=='__main__':unittest.main()
