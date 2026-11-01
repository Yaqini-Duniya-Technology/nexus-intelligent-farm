import copy
import unittest
try:
    from nexus.farm_app.review_readiness import summarize
except ModuleNotFoundError:
    from review_readiness import summarize


class ReviewReadinessTests(unittest.TestCase):
    def bundle(self):
        return {'id':5,'captured_at':'2026-10-13T16:51:35+00:00','payload':{
            'adviser_reviews':[],'photo_metadata':[],'task_actions':[], 'raw_followups':[],
            'latest_field_context':{'soil_type':'unknown','water_access':'unknown','resources':''},
            'voice_clarification_history':[{'id':1,'payload':{
                'questions':['Growth stage?'],'answers':['Unknown']}}]}}

    def test_record_gaps_and_explicit_unknown(self):
        result = summarize(self.bundle())
        self.assertEqual(len(result['record_findings']),7)
        self.assertEqual(result['season_context']['status'], 'not_captured')
        self.assertEqual(result['clarification_questions_for_human_assessment'][0]['assessment'],'explicit_unknown')

    def test_free_text_not_automatically_resolved(self):
        bundle = self.bundle()
        bundle['payload']['voice_clarification_history'][0]['payload']['answers']=['The growth stage is unknown; inspection is needed.']
        self.assertEqual(summarize(bundle)['clarification_questions_for_human_assessment'][0]['assessment'],'human_assessment_required')

    def test_newest_entry_by_saved_id_and_no_mutation(self):
        bundle = self.bundle()
        bundle['payload']['voice_clarification_history'].append({'id':2,'payload':{'questions':['Growth stage?'],'answers':['Mature']}})
        original = copy.deepcopy(bundle)
        self.assertEqual(summarize(bundle)['latest_clarification_entry_id'],2)
        self.assertEqual(bundle,original)

    def test_older_bundle_supported(self):
        result = summarize({'id':1,'captured_at':'time','payload':{}})
        self.assertIsNone(result['record_counts']['adviser_reviews'])
        self.assertIsNone(result['latest_clarification_entry_id'])
        self.assertTrue(any('earlier bundle' in s for s in result['record_findings']))


if __name__ == '__main__': unittest.main()
