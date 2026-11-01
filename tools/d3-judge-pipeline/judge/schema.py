import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object', 'additionalProperties': False,
    'required': ['risk', 'predicted_class', 'severity', 'effect_summary', 'evidence_spans',
                 'missing_context', 'review_required', 'reason_codes', 'policy_refs'],
    'properties': {
        'risk': {'type': ['string', 'null'], 'pattern': '^CAT-[0-9]+\\.[0-9]+$'},
        'predicted_class': {'enum': ['allow', 'ask', 'deny', None]},
        'severity': {'enum': ['low', 'medium', 'high', 'critical', None]},
        'effect_summary': {'type': 'string', 'minLength': 1},
        'evidence_spans': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}},
        'missing_context': {'type': 'array', 'items': {'type': 'string'}},
        'review_required': {'type': 'boolean'},
        'reason_codes': {'type': 'array', 'items': {'type': 'string'}},
        'policy_refs': {'type': 'array', 'items': {'type': 'string'}},
    },
}
TAXONOMY = {'CAT-0.0'} | {f'CAT-{n}.{m}' for n, count in {1:5,2:4,3:5,4:5,5:5,6:5,7:5,8:3,9:4}.items() for m in range(1,count+1)}

def validate_response(response, command):
    errors = [x.message for x in Draft202012Validator(SCHEMA).iter_errors(response)]
    if errors: return errors
    if response['risk'] is not None and response['risk'] not in TAXONOMY:
        errors.append('unknown_risk')
    if any(span not in command for span in response['evidence_spans']):
        errors.append('evidence_not_literal_substring')
    if response['predicted_class'] is None and not response['review_required']:
        errors.append('abstention_requires_review')
    if response['predicted_class'] is not None and (response['severity'] is None or not response['evidence_spans']):
        errors.append('prediction_requires_severity_and_evidence')
    if response['risk'] is None and not response['review_required']:
        errors.append('unknown_risk_requires_review')
    return errors

if __name__ == '__main__':
    Path(__file__).with_suffix('.json').write_text(json.dumps(SCHEMA, indent=2)+'\n')
