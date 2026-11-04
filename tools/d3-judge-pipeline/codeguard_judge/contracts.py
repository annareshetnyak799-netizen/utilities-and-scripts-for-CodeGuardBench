"""Versioned contracts. Predictions remain proposals, not human decisions."""
from jsonschema import Draft202012Validator
from judge.schema import SCHEMA as LEGACY
from .policy import TAXONOMY,refs_for
SCHEMA_VERSION='cascade-contract-1'
SCHEMA={**LEGACY,'required':LEGACY['required']+['risk_identifiable'],'properties':{**LEGACY['properties'],'risk_identifiable':{'type':'boolean'}}}
SEMANTIC_SCHEMA={'type':'object','additionalProperties':False,'required':['actions','missing_context'],'properties':{'actions':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['effect','evidence','conditional','wrapper'],'properties':{'effect':{'type':'string'},'evidence':{'type':'string','minLength':1},'conditional':{'type':'boolean'},'wrapper':{'type':['string','null']}}}},'missing_context':{'type':'array','items':{'type':'string'}}}}
CRITIC_SCHEMA={'type':'object','additionalProperties':False,'required':['verdict','reason','policy_refs','evidence_spans'],'properties':{'verdict':{'enum':['agree','disagree','insufficient_evidence']},'reason':{'type':'string','minLength':1},'policy_refs':{'type':'array','items':{'type':'string'}},'evidence_spans':{'type':'array','items':{'type':'string'}}}}
def validate(value,command,kind='classifier'):
 schema={'classifier':SCHEMA,'semantic':SEMANTIC_SCHEMA,'critic':CRITIC_SCHEMA}[kind]
 errors=['schema:'+e.validator for e in Draft202012Validator(schema).iter_errors(value)]
 if errors:return errors
 if kind=='semantic':
  if any(a['evidence'] not in command for a in value['actions']):errors.append('nonliteral_evidence')
  return errors
 spans=value['evidence_spans']
 if any(not x or x not in command for x in spans):errors.append('nonliteral_evidence')
 if kind=='critic':
  allowed=TAXONOMY|refs_for(None)
  if not set(value['policy_refs'])<=allowed:errors.append('unknown_policy_ref')
  return errors
 risk=value['risk'];cls=value['predicted_class']
 if risk is not None and risk not in TAXONOMY:errors.append('unknown_risk')
 if not set(value['policy_refs'])<=refs_for(risk):errors.append('inapplicable_policy_ref')
 if cls is not None:
  if risk is None or value['severity'] is None or risk not in value['policy_refs']:errors.append('missing_prediction_basis')
  if not spans:errors.append('missing_evidence')
  # Utility name alone cannot establish the mode/target of a dangerous operation.
  if cls!='allow' and all(len(x.split())<2 and not x.startswith('-') and '/' not in x for x in spans):errors.append('insufficient_causal_evidence')
 if (cls is None or risk is None or value['missing_context']) and not value['review_required']:errors.append('missing_review_flag')
 return errors

def abstain(reason):
 return dict(risk=None,predicted_class=None,severity=None,effect_summary=reason,evidence_spans=[],missing_context=[reason],review_required=True,reason_codes=[reason],policy_refs=[],risk_identifiable=False)
def safety(cls):return {'allow':'safe','ask':'unsafe','deny':'unsafe',None:None}[cls]
