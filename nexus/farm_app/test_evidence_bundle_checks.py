import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

try:
    from nexus.farm_app import evidence_quality as module
except ModuleNotFoundError as error:
    if error.name not in ('nexus', 'nexus.farm_app'):
        raise
    spec = importlib.util.spec_from_file_location('quality', Path(__file__).with_name('evidence_quality.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def bundle(bid, adviser=False):
    payload = {'adviser_reviews': [{'id': 1}] if adviser else [],
               'photo_metadata': [], 'voice_clarification_history': [{'id': 2}, {'id': 1}],
               'observation': {'observed_at': '2026-10-11T09:43:00+00:00'},
               'latest_field_context': {'soil_type': 'unknown', 'water_access': 'unknown',
                                       'resources': '', 'recorded_at': '2026-10-13T09:00:00+00:00'}}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return {'id': bid, 'observation_id': 5, 'captured_at': '2026-10-13T18:00:00+00:00',
            'content_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'payload': payload}


class EvidenceBundleCheckTests(unittest.TestCase):
    def saved(self):
        reviewed = bundle(7, True)
        return {'id': 3, 'captured_at': '2026-10-15T12:18:11+00:00', 'hash_matches': True,
                'payload': {'supporting_bundle': bundle(5),
                            'events': [{'id': 3, 'kind': 'action', 'occurred_at': '2026-10-13T18:01:26+00:00'}],
                            'reviews': [{'id': 2, 'evidence_bundle_id': 7, 'evidence_bundle_sha256': reviewed['content_sha256']}],
                            'review_evidence_bundles': [{'bundle': reviewed, 'review_ids': [2]}]}}

    def codes(self, summary):
        return {f['code'] for f in summary['findings']}

    def test_each_bundle_has_id_and_distinct_checks(self):
        result = module.summarize(self.saved())
        original, reviewed = result['bundle_checks']
        self.assertEqual([original['bundle_id'], reviewed['bundle_id']], [5, 7])
        self.assertEqual(reviewed['referencing_review_ids'], [2])
        self.assertTrue(reviewed['content_hash_matches'])
        self.assertEqual(reviewed['counts']['clarification_entries'], 2)
        self.assertIn('no_adviser_review_captured', {f['code'] for f in original['findings']})
        self.assertNotIn('no_adviser_review_captured', {f['code'] for f in reviewed['findings']})
        self.assertIn('action_without_outcome', self.codes(result))
        self.assertEqual(result['counts'], {'actions': 1, 'outcome_reports': 0, 'reviews': 1})

    def test_no_mutation_and_repeat_is_stable(self):
        saved = self.saved()
        before = copy.deepcopy(saved)
        first = module.summarize(saved)
        self.assertEqual(saved, before)
        self.assertEqual(module.summarize(saved), first)

    def test_legacy_snapshot_without_bundle_capture(self):
        saved = self.saved()
        del saved['payload']['review_evidence_bundles']
        result = module.summarize(saved)
        self.assertEqual(result['review_evidence_capture_status'], 'not_recorded_in_older_snapshot')
        self.assertEqual(len(result['bundle_checks']), 1)
        self.assertNotIn('review_evidence_not_captured', self.codes(result))

    def test_empty_new_capture_and_missing_reference(self):
        saved = self.saved()
        saved['payload']['review_evidence_bundles'] = []
        result = module.summarize(saved)
        self.assertEqual(result['review_evidence_capture_status'], 'captured')
        self.assertIn('review_evidence_not_captured', self.codes(result))
        saved['payload']['reviews'] = []
        self.assertNotIn('review_evidence_not_captured', self.codes(module.summarize(saved)))

    def test_tampered_bundle_and_reference_detected(self):
        saved = self.saved()
        saved['payload']['review_evidence_bundles'][0]['bundle']['payload']['photo_metadata'] = [{'id': 4}]
        codes = self.codes(module.summarize(saved))
        self.assertIn('bundle_content_hash_mismatch', codes)
        self.assertIn('photo_review_needed', codes)
        saved['payload']['reviews'][0]['evidence_bundle_sha256'] = 'bad'
        self.assertIn('review_evidence_reference_mismatch', self.codes(module.summarize(saved)))

    def test_wrong_observation_detected(self):
        saved = self.saved()
        saved['payload']['review_evidence_bundles'][0]['bundle']['observation_id'] = 999
        self.assertIn('review_evidence_observation_mismatch', self.codes(module.summarize(saved)))

    def test_existing_outcome_time_checks_preserved(self):
        for value, code in [('2026-10-13T18:01:26+00:00', 'same_time_report'),
                            ('2026-10-12T18:01:26+00:00', 'outcome_predates_action'),
                            ('invalid', 'event_time_unavailable')]:
            with self.subTest(code=code):
                saved = self.saved()
                saved['payload']['events'].append({'id': 4, 'kind': 'outcome', 'action_id': 3, 'occurred_at': value})
                codes = self.codes(module.summarize(saved))
                self.assertIn(code, codes)
                self.assertIn('reported_outcome_unverified', codes)
                self.assertNotIn('action_without_outcome', codes)

    def test_snapshot_mismatch_and_orphan_outcome(self):
        saved = self.saved()
        saved['hash_matches'] = False
        saved['payload']['events'] = [{'id': 4, 'kind': 'outcome', 'action_id': 999}]
        codes = self.codes(module.summarize(saved))
        self.assertTrue({'content_hash_mismatch', 'no_linked_work', 'linked_action_missing'} <= codes)


if __name__ == '__main__':
    unittest.main()
