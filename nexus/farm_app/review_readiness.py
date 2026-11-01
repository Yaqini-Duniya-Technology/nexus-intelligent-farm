"""Descriptive checks of a saved bundle, without interpreting free text."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def summarize(bundle):
    payload = bundle['payload']
    captured = {}
    for key in ('adviser_reviews', 'photo_metadata', 'task_actions', 'raw_followups'):
        value = payload.get(key)
        captured[key] = len(value) if isinstance(value, list) else None
    linked = payload.get('linked_human_decisions')
    decision_counts = {'human_decisions': None, 'decision_actions': None, 'decision_outcomes': None}
    if isinstance(linked, list):
        decision_counts['human_decisions'] = len(linked)
        if 'decision_events' not in payload.get('unavailable_tables', []) and all(
                isinstance(item, dict) and isinstance(item.get('events'), list) for item in linked):
            events = [event for item in linked for event in item['events']]
            decision_counts['decision_actions'] = sum(event.get('kind') == 'action' for event in events)
            decision_counts['decision_outcomes'] = sum(event.get('kind') == 'outcome' for event in events)
    from nexus.farm_app.season_context import assess
    season_context = assess(payload)
    from nexus.farm_app.field_inspections import assess as assess_inspections
    inspections = assess_inspections(payload)
    findings = list(season_context["findings"]) + inspections['findings']
    if captured['adviser_reviews'] == 0:
        findings.append('No adviser review was captured. This does not establish whether a consultation occurred later.')
    if captured['photo_metadata'] == 0:
        findings.append('No photo metadata was captured. This does not establish whether photos exist elsewhere.')
    context = payload.get('latest_field_context')
    for key in ('soil_type', 'water_access', 'resources'):
        value = context.get(key) if isinstance(context, dict) else None
        if value is None or (isinstance(value, str) and value.strip().lower() in ('', 'unknown', 'not recorded')):
            findings.append(key.replace('_', ' ').capitalize() + ' is absent or recorded as unknown. A human should assess its relevance.')
    history = payload.get('voice_clarification_history')
    latest = None
    questions = []
    if isinstance(history, list) and history:
        usable = [entry for entry in history if isinstance(entry, dict) and type(entry.get('id')) is int]
        if len(usable) != len(history):
            findings.append('Some clarification entries could not be assessed.')
        if usable:
            latest = max(usable, key=lambda entry: entry['id'])
            answer_payload = latest.get('payload')
            if isinstance(answer_payload, dict):
                qs, answers = answer_payload.get('questions'), answer_payload.get('answers')
                if isinstance(qs, list) and isinstance(answers, list) and len(qs) == len(answers):
                    for question, answer in zip(qs, answers):
                        if not isinstance(question, str) or not isinstance(answer, str):
                            findings.append('A clarification question or answer could not be assessed.')
                            continue
                        unknown = answer.strip().lower().rstrip('.') == 'unknown'
                        questions.append({'question': question, 'saved_answer': answer,
                            'assessment': 'explicit_unknown' if unknown else 'human_assessment_required'})
                else:
                    findings.append('Latest clarification questions and answers could not be paired.')
    elif 'voice_clarification_history' not in payload:
        findings.append('This earlier bundle did not capture clarification history.')
    else:
        findings.append('No clarification answer entries were captured.')
    resources=payload.get('resource_case_links')
    resource_checks={'status':'not_captured','links':None,'active':None,'withdrawn':None,'changed_targets':None}
    if isinstance(resources,dict):
        links=resources.get('links',[])
        resource_checks={'status':'captured','links':len(links),'active':sum(r['payload']['values']['status']=='active' for r in links),'withdrawn':sum(r['payload']['values']['status']=='withdrawn' for r in links),'changed_targets':sum(r.get('target_check_at_capture')=='changed_since_link' for r in links)}
        if resource_checks['changed_targets']:findings.append('A selected resource differed from its frozen link copy at capture. Assess the saved versions; no current content is substituted.')
    return {'summary_version': 'saved-bundle-review-checks-v4','resource_case_links':resource_checks, 'season_context': season_context, 'inspections': inspections,
            'bundle_id': bundle['id'], 'bundle_captured_at': bundle['captured_at'],
            'record_counts': captured, 'linked_decision_counts': decision_counts, 'latest_clarification_entry_id': latest['id'] if latest else None,
            'record_findings': findings, 'clarification_questions_for_human_assessment': questions,
            'limitations': [
                'Uses this saved bundle only. Later farm edits are not included.',
                'Free-text answers are not classified as resolved or unresolved. Only an answer consisting of Unknown is marked explicitly unknown.',
                'The newest saved clarification entry is shown for assessment; earlier versions remain in the bundle.',
                'No readiness score, diagnosis, treatment recommendation or approval is calculated.',
                'No farm record, task or saved bundle is changed.']}


def main():
    parser = argparse.ArgumentParser(description='Check saved NEXUS review records')
    parser.add_argument('--bundle-id', required=True, type=int)
    parser.add_argument('--database', default='nexus-farm.sqlite3')
    args = parser.parse_args()
    try:
        if args.bundle_id < 1:
            raise ValueError('Use a positive bundle ID')
        path = Path(args.database).resolve()
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM decision_review_bundles WHERE id=?', (args.bundle_id,)).fetchone()
            if row is None:
                raise ValueError('Review bundle not found')
            bundle = dict(row)
            bundle['payload'] = json.loads(bundle['payload'])
        print(json.dumps(summarize(bundle), indent=2, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f'Could not read review readiness: {error}\n')


if __name__ == '__main__':
    main()
