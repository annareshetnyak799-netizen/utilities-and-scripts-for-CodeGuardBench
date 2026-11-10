"""Class dominance is approved; PI-20/21 intentionally remain unresolved."""
from .schemas import aggregate_class


def aggregate(decisions):
    verdict = aggregate_class(decisions)
    reasons = sorted({d['review_reason'] for d in decisions if d.get('review_reason')})
    resolved = [d for d in decisions if d.get('class')]
    primary = None
    if verdict:
        risks = {d['risk'] for d in resolved if d['class'] == verdict}
        if len(risks) == 1:
            primary = next(iter(risks))
        elif len(risks) > 1:
            reasons.append('aggregation_tie_unresolved:PI-21')
    severity = None
    if len(decisions) == 1 and len(resolved) == 1:
        severity = resolved[0]['severity']
    elif len(decisions) > 1:
        reasons.append('aggregation_severity_unapproved:PI-20')
    return dict(operational_verdict=verdict,
                proposed_final_class=verdict if not any(d.get('review_reason') for d in decisions) else None,
                primary_risk=primary, severity=severity,
                review_status='needs_review' if reasons else 'proposed',
                review_reasons=sorted(set(reasons)), human_status='unreviewed')
