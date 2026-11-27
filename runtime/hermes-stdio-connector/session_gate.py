"""Pure acceptance gate; adapters must supply independently observed evidence."""
from datetime import datetime, timezone

def assess(required, observations, session_id, now=None):
    now = now or datetime.now(timezone.utc)
    if not session_id or not required or len(set(required)) != len(required):
        raise ValueError('nonempty unique requirements and session identity required')
    gaps = {}
    for capability in required:
        r = observations.get(capability, {})
        try:
            age = (now - datetime.fromisoformat(r['observed_at'])).total_seconds()
            valid = (r['session_id'] == session_id and 0 <= age <= 300
                     and r['authenticated'] is True and r['probe_ok'] is True
                     and r['read_only'] is True and bool(r['receipt_id']))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            gaps[capability] = 'UNVERIFIED'
    return {'state': 'DEGRADED' if gaps else 'READY', 'gaps': gaps,
            'session_id': session_id, 'scope': 'supplied evidence only'}
