"""Read-only record checks over a saved decision-cycle payload."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace


def parse_time(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def bundle_checks(record, reference, role, review_ids=None):
    """Check one frozen bundle without consulting live records."""
    findings = []

    def add(code, suffix, message):
        findings.append({'code': code, 'reference': reference + suffix,
                         'message': message})

    bundle = record.get('payload')
    valid_payload = isinstance(bundle, dict)
    matches = False
    if valid_payload:
        try:
            raw = json.dumps(bundle, sort_keys=True, ensure_ascii=False, allow_nan=False)
            matches = hashlib.sha256(raw.encode('utf-8')).hexdigest() == record.get('content_sha256')
        except (TypeError, ValueError):
            pass
    if not matches:
        add('bundle_content_hash_mismatch', '',
            'The frozen bundle payload is missing, invalid or does not match its stored content hash.')
    if not valid_payload:
        bundle = {}
    label = f"{role} bundle #{record.get('id', 'unknown')}"
    if not bundle.get('adviser_reviews'):
        add('no_adviser_review_captured', '.adviser_reviews',
            f'No adviser review was captured in {label}. This does not establish whether a later consultation occurred.')
    photos = bundle.get('photo_metadata') or []
    if photos:
        add('photo_review_needed', '.photo_metadata',
            f'Human review must check image source labels and relevance in {label}. Metadata alone does not verify a farm image.')
    else:
        add('no_photo_metadata_captured', '.photo_metadata',
            f'No photo metadata was captured in {label}.')
    context = bundle.get('latest_field_context') or {}
    if not context:
        add('field_context_missing', '.latest_field_context', 'No field context was captured.')
    for key in ('soil_type', 'water_access', 'resources'):
        value = context.get(key)
        if not value or str(value).strip().lower() == 'unknown':
            add('field_detail_missing', '.latest_field_context.' + key,
                'This field detail is absent or recorded as unknown; assess whether it matters to the decision.')
    observation = bundle.get('observation') or {}
    context_time = parse_time(context.get('recorded_at'))
    observation_time = parse_time(observation.get('observed_at'))
    if context_time and observation_time and context_time > observation_time:
        add('context_recorded_later', '.latest_field_context',
            'Field context was recorded after the observation. It does not by itself establish the crop stage at observation time.')
    from nexus.farm_app.season_context import assess
    season_context = assess(bundle)
    for message in season_context['findings']:
        add('season_context_' + season_context['status'], '.observation_season_history', message)
    from nexus.farm_app.field_inspections import assess as assess_inspections
    inspections = assess_inspections(bundle)
    for message in inspections['findings']:
        add('inspections_' + inspections['status'], '.field_inspections', message)
    history = bundle.get('voice_clarification_history') or []
    return {
        'season_context': season_context,
        'inspections': inspections,
        'role': role, 'bundle_id': record.get('id'),
        'observation_id': record.get('observation_id'),
        'reference': reference, 'captured_at': record.get('captured_at'),
        'referencing_review_ids': list(review_ids or []),
        'content_hash_matches': matches,
        'counts': {'adviser_reviews': len(bundle.get('adviser_reviews') or []),
                   'photo_metadata': len(photos),
                   'clarification_entries': len(history)},
        'findings': findings,
    }


def summarize(saved):
    payload = saved['payload']
    events = payload.get('events') or []
    actions = [e for e in events if e.get('kind') == 'action']
    outcomes = [e for e in events if e.get('kind') == 'outcome']
    reviews = payload.get('reviews') or []
    action_map = {a['id']: a for a in actions}
    findings = []

    def add(code, reference, message):
        findings.append({'code': code, 'reference': reference, 'message': message})

    if not saved['hash_matches']:
        add('content_hash_mismatch', 'snapshot',
            'The captured payload does not match its stored content hash.')
    original = payload.get('supporting_bundle') or {}
    checks = [bundle_checks(original, 'supporting_bundle', 'original supporting')]
    findings.extend(checks[0]['findings'])
    has_review_evidence = 'review_evidence_bundles' in payload
    entries = payload.get('review_evidence_bundles') or []
    review_map = {r['id']: r for r in reviews}
    captured_links = set()
    for index, entry in enumerate(entries):
        reference = f'review_evidence_bundles[{index}].bundle'
        record = entry['bundle']
        ids = entry.get('review_ids') or []
        check = bundle_checks(record, reference, 'reviewed evidence', ids)
        checks.append(check)
        findings.extend(check['findings'])
        if record.get('observation_id') != original.get('observation_id'):
            add('review_evidence_observation_mismatch', reference,
                'This reviewed bundle does not identify the same observation as the original supporting bundle.')
        if not ids:
            add('review_evidence_reference_missing', reference,
                'No captured review IDs reference this frozen evidence entry.')
        for rid in ids:
            review = review_map.get(rid)
            if (review is None or review.get('evidence_bundle_id') != record.get('id')
                    or review.get('evidence_bundle_sha256') != record.get('content_sha256')):
                add('review_evidence_reference_mismatch', reference,
                    f'Captured review #{rid} is absent or its bundle ID/hash does not match this frozen bundle.')
            else:
                captured_links.add(rid)
    if has_review_evidence:
        for review in reviews:
            if review.get('evidence_bundle_id') is not None and review['id'] not in captured_links:
                add('review_evidence_not_captured', f"review:{review['id']}",
                    'This review references evidence without a matching frozen bundle and review link in the snapshot.')
    if not actions:
        add('no_linked_work', 'events', 'No action under this decision was captured.')
    for action in actions:
        if not any(o.get('action_id') == action['id'] for o in outcomes):
            add('action_without_outcome', f"action:{action['id']}",
                'No outcome report was linked to this action at capture time.')
    for outcome in outcomes:
        reference = f"outcome:{outcome['id']}"
        add('reported_outcome_unverified', reference,
            'This is a user-entered outcome report; chronological linkage does not establish causation or effectiveness.')
        action = action_map.get(outcome.get('action_id'))
        if action is None:
            add('linked_action_missing', reference, 'The linked action is absent from this captured cycle.')
            continue
        observed = parse_time(outcome.get('occurred_at'))
        performed = parse_time(action.get('occurred_at'))
        if observed is None or performed is None:
            add('event_time_unavailable', reference,
                'An event time is missing, invalid or lacks a timezone.')
        elif observed < performed:
            add('outcome_predates_action', reference,
                'The recorded outcome time predates the linked action time.')
        elif observed == performed:
            add('same_time_report', reference,
                'The outcome and action have the same recorded time. This is not evidence of a later change following the work.')
    return {
        'summary_version': 'evidence-record-checks-v4',
        'snapshot_id': saved['id'], 'captured_at': saved['captured_at'],
        'content_hash_matches': saved['hash_matches'],
        'counts': {'actions': len(actions), 'outcome_reports': len(outcomes), 'reviews': len(reviews)},
        'review_evidence_capture_status': 'captured' if has_review_evidence else 'not_recorded_in_older_snapshot',
        'bundle_checks': checks,
        'findings': findings,
        'human_review_questions': [
            'Which crop season and plants do these observations describe?',
            'What specific visible changes support each reported result, and how many plants were checked?',
            'Are comparison observations and product/crop stages relevant to the same case?',
            'What cause remains unconfirmed, and what additional examination is needed?',
            'Which resource constraints are relevant to the chosen next step?',
        ],
        'limitations': [
            'Checks use this saved capture only, not current farm records.',
            'Each bundle is assessed separately; later evidence does not replace the original supporting bundle.',
            'Older snapshots may not contain reviewed evidence bundle contents. Missing historical captures are not fetched from current records.',
            'Bundle counts are per capture; repeated records across bundles are not independent evidence.',
            'Clarification entries are counted, not classified as resolving questions.',
            'No completeness score, diagnosis or treatment recommendation is calculated.',
            'Free-text findings are not automatically interpreted or independently verified.',
            'The questions are prompts for human review, not established defects in the records.',
            'Hashes check consistency, not agricultural accuracy or model/reviewer identity.',
            'Plans, tasks, reviews and captured evidence are unchanged.',
        ],
    }


def main():
    # Lazy import also permits pure summary checks without loading the web server.
    from nexus.farm_app.decision_cycles import read_cycles
    parser = argparse.ArgumentParser(description='Review evidence record checks for a saved decision cycle')
    parser.add_argument('--database', default='nexus-farm.sqlite3')
    parser.add_argument('--snapshot-id', type=int, required=True)
    args = parser.parse_args()
    if args.snapshot_id < 1:
        parser.error('Use a positive snapshot ID')
    try:
        saved = read_cycles(SimpleNamespace(path=args.database), args.snapshot_id)
        result = summarize(saved)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Evidence summary failed: {error}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
