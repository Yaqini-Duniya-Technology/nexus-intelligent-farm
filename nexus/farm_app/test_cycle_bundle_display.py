"""Exercise the shipped viewer functions without starting the web server."""
import ast
import copy
import hashlib
import html
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def load_functions():
    path = Path(__file__).with_name('decision_cycles.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    wanted = {'read_cycles', 'render_check_findings', 'render_check_summary'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    scope = {'text': lambda value: html.escape(str(value)),
             'local_time': lambda value: 'Lagos: ' + value,
             'sqlite3': sqlite3, 'closing': closing, 'Path': Path,
             'hashlib': hashlib, 'canonical': canonical, 'json': json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


class CycleBundleDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = load_functions()

    def summary(self):
        first = {'code': 'field_detail_missing', 'reference': 'supporting_bundle.latest_field_context.soil_type', 'message': 'Soil type unknown.'}
        second = {'code': 'no_photo_metadata_captured', 'reference': 'review_evidence_bundles[0].bundle.photo_metadata', 'message': 'No photos captured in bundle #7.'}
        return {'summary_version': 'evidence-record-checks-v2', 'content_hash_matches': True,
                'counts': {'actions': 1, 'outcome_reports': 0, 'reviews': 3},
                'review_evidence_capture_status': 'captured',
                'bundle_checks': [
                    {'role': 'original supporting', 'bundle_id': 5, 'observation_id': 5,
                     'captured_at': '2026-10-13T16:51:35+00:00', 'content_hash_matches': True,
                     'referencing_review_ids': [], 'counts': {'clarification_entries': 1}, 'findings': [first]},
                    {'role': 'reviewed evidence', 'bundle_id': 7, 'observation_id': 5,
                     'captured_at': '2026-10-13T18:40:52+00:00', 'content_hash_matches': True,
                     'referencing_review_ids': [2], 'counts': {'clarification_entries': 2}, 'findings': [second]}],
                'findings': [first, second, {'code': 'action_without_outcome', 'reference': 'action:3', 'message': 'No outcome linked to action #3.'}],
                'human_review_questions': ['Which crop season?'], 'limitations': ['Saved capture only.']}

    def render(self, summary):
        return self.functions['render_check_summary'](summary)

    def test_separate_bundles_counts_and_links(self):
        output = self.render(self.summary())
        self.assertIn('Original supporting bundle #5', output)
        self.assertIn('Reviewed evidence bundle #7', output)
        self.assertIn('Referencing review IDs</dt><dd>2</dd>', output)
        self.assertIn('Clarification entries</dt><dd>1</dd>', output)
        self.assertIn('Clarification entries</dt><dd>2</dd>', output)
        self.assertIn('Lagos: 2026-10-13T18:40:52', output)
        self.assertIn('not independent evidence', output)

    def test_findings_render_once(self):
        output = self.render(self.summary())
        self.assertEqual(output.count('Soil type unknown.'), 1)
        self.assertEqual(output.count('No photos captured in bundle #7.'), 1)
        self.assertEqual(output.count('No outcome linked to action #3.'), 1)

    def test_untrusted_values_are_escaped(self):
        summary = self.summary()
        attack = '<script>alert(1)</script>'
        summary['bundle_checks'][1]['role'] = attack
        summary['bundle_checks'][1]['referencing_review_ids'] = [attack]
        summary['human_review_questions'] = [attack]
        summary['limitations'] = [attack]
        summary['findings'].append({'code': attack, 'reference': attack, 'message': attack})
        output = self.render(summary)
        self.assertNotIn('<script>', output.lower())
        self.assertIn('&lt;script&gt;', output)

    def test_mismatches_are_visible(self):
        summary = self.summary()
        summary['content_hash_matches'] = False
        summary['bundle_checks'][1]['content_hash_matches'] = False
        self.assertEqual(self.render(summary).count('MISMATCH'), 2)

    def test_legacy_summary_and_snapshot(self):
        summary = self.summary()
        summary['bundle_checks'] = summary['bundle_checks'][:1]
        summary['review_evidence_capture_status'] = 'not_recorded_in_older_snapshot'
        self.assertIn('older snapshot', self.render(summary))
        del summary['bundle_checks']
        output = self.render(summary)
        self.assertIn('No outcome linked to action #3.', output)
        self.assertNotIn('Checks by captured bundle', output)

    def test_empty_findings_and_input_unchanged(self):
        summary = self.summary()
        summary['findings'] = []
        for check in summary['bundle_checks']:
            check['findings'] = []
        before = copy.deepcopy(summary)
        self.assertIn('does not verify the evidence', self.render(summary))
        self.assertEqual(summary, before)

    def test_read_and_render_do_not_change_database_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.sqlite3'
            payload = {'snapshot_version': 'decision-cycle-v2'}
            raw = canonical(payload)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE decision_cycle_snapshots(id INTEGER PRIMARY KEY, decision_id INTEGER, captured_at TEXT, content_sha256 TEXT, payload TEXT)')
                db.execute('INSERT INTO decision_cycle_snapshots VALUES(4,2,?,?,?)',
                           ('2026-10-17T14:48:01+00:00', hashlib.sha256(raw.encode()).hexdigest(), raw))
            before = path.read_bytes()
            saved = self.functions['read_cycles'](SimpleNamespace(path=path), 4)
            self.assertTrue(saved['hash_matches'])
            self.render(self.summary())
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
