"""Versioned real-farm observation contract and transparent workflow triage.

No agronomic risk thresholds, trained predictions, or simulator policy changes.
"""
import math
from datetime import datetime, timezone, timedelta

CONTRACT_VERSION = 'real-farm-observation-v1'
RULE_VERSION = 'human-review-v1'

def normalize(data, now=None):
    now = now or datetime.now(timezone.utc)
    observed_at = data.get('observed_at') or now.isoformat()
    if not isinstance(observed_at, str):
        raise ValueError('Observation time must be an ISO timestamp')
    try:
        timestamp = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Use a valid observation time') from None
    if timestamp.tzinfo is None:
        raise ValueError('Observation time must include a timezone')
    timestamp = timestamp.astimezone(timezone.utc)
    if timestamp > now + timedelta(minutes=5):
        raise ValueError('Observation time cannot be in the future')
    category = data.get('category', 'general')
    source = data.get('source', 'farmer')
    condition = data.get('condition', 'unknown')
    if category not in ('general', 'crop_health', 'water', 'pest', 'operations'):
        raise ValueError('Choose a valid observation category')
    if source not in ('farmer', 'adviser', 'sensor'):
        raise ValueError('Choose a valid observation source')
    if condition not in ('unknown', 'stable', 'worsening'):
        raise ValueError('Choose a valid field condition')
    raw = data.get('soil_moisture_pct')
    if raw is None or raw == '':
        moisture = None
    else:
        if isinstance(raw, bool):
            raise ValueError('Soil moisture must be a number')
        try:
            moisture = float(raw)
        except (TypeError, ValueError):
            raise ValueError('Soil moisture must be a number') from None
        if not math.isfinite(moisture) or not 0 <= moisture <= 100:
            raise ValueError('Soil moisture must be between 0 and 100 percent')
    method = data.get('moisture_method') or None
    if method not in (None, 'volumetric_sensor'):
        raise ValueError('Unsupported moisture measurement method')
    if moisture is not None and method is None:
        raise ValueError('Specify the moisture measurement method')
    if moisture is None and method is not None:
        raise ValueError('Add a moisture measurement or clear its method')
    return dict(observed_at=timestamp.isoformat(), category=category, source=source,
                condition=condition, soil_moisture_pct=moisture,
                moisture_method=method, contract_version=CONTRACT_VERSION)

def review(observation, now=None):
    now = now or datetime.now(timezone.utc)
    observed = datetime.fromisoformat(observation['observed_at'])
    age = now - observed
    reasons = []
    missing = []
    priority = 'routine'
    if observation['condition'] == 'worsening':
        priority = 'prompt'
        reasons.append('The observer reported worsening conditions; arrange a prompt human review.')
    else:
        reasons.append('The observation requires verification before choosing an intervention.')
    if age > timedelta(hours=24):
        missing.append('updated field observation')
        reasons.append('This record was over 24 hours old when submitted. Refresh it before making a decision; 24 hours is a workflow freshness rule, not an agronomic threshold.')
    if observation['category'] == 'water' and observation['soil_moisture_pct'] is None:
        missing.append('measured soil moisture with a documented method')
        reasons.append('No soil moisture measurement was supplied. Missing data is not interpreted as zero.')
    if observation['category'] in ('crop_health', 'pest'):
        missing.append('expert verification and symptom evidence')
        reasons.append('Symptoms alone do not establish a disease or pest diagnosis.')
    if observation['soil_moisture_pct'] is not None:
        reasons.append('Moisture is recorded as volumetric water content (%); no irrigation threshold is inferred without soil, crop and sensor context.')
    return dict(priority=priority, explanation=' '.join(reasons),
                missing_information=missing, rule_version=RULE_VERSION,
                recommendation='Inspect the field, verify the recorded evidence and document findings with a qualified adviser before selecting an intervention.')
