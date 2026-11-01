import copy
import unittest
try:
    from nexus.farm_app.review_bundles import bundle_page, clarification_section
except ModuleNotFoundError:
    from review_bundles import bundle_page, clarification_section


class ClarificationDisplayTests(unittest.TestCase):
    def entry(self):
        return {'id': 1, 'observation_id': 5, 'link_id': 1,
                'recorded_at': '2026-10-13T05:00:00+00:00',
                'content_sha256': 'test-hash', 'payload': {
                    'reporter': 'Test farmer', 'review_id': 3, 'review_hash': 'review-hash',
                    'questions': ['Growth stage?'], 'answers': ['Unknown']}}

    def test_older_bundle_and_empty_history_distinct(self):
        self.assertIn('earlier bundle did not capture', clarification_section({}))
        self.assertIn('No clarification answers captured', clarification_section({'voice_clarification_history': []}))

    def test_questions_answers_and_lagos_time_displayed(self):
        result = clarification_section({'voice_clarification_history': [self.entry()]})
        for expected in ['Growth stage?', 'Unknown', 'Test farmer', '13/10/2026, 06:00:00 (Lagos time)', 'Answer entry #1']:
            self.assertIn(expected, result)

    def test_html_text_escaped(self):
        entry = self.entry()
        entry['payload']['answers'] = ['<script>alert(1)</script>']
        result = clarification_section({'voice_clarification_history': [entry]})
        self.assertNotIn('<script>', result)
        self.assertIn('&lt;script&gt;', result)

    def test_bundle_render_preserves_saved_payload(self):
        bundle = {'id':5,'observation_id':5,'captured_at':'2026-10-13T05:00:00+00:00',
                  'content_sha256':'test','payload':{'bundle_version':'human-review-bundle-v3',
                    'voice_clarification_history':[self.entry()]}}
        original = copy.deepcopy(bundle)
        self.assertIn('Voice clarification answers at capture', bundle_page(bundle))
        self.assertEqual(bundle, original)

    def test_malformed_history_shows_message(self):
        self.assertIn('could not be displayed', clarification_section({'voice_clarification_history':'bad'}))


if __name__ == '__main__': unittest.main()
