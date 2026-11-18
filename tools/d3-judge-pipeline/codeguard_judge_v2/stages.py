import json
from pathlib import Path
from .common import digest, dumps
from .parser import PARSER_VERSION
from .policy_registry import TAXONOMY, RISK_CODES, materialize
from .schemas import Stage1Result, Stage2Result, validate_stage1
from . import class_mode

# Full Guideline scope CAT-0..9: 42 risk codes, including CAT-7/8/9.
assert len(RISK_CODES) == 42

PROMPTS = {s: (Path(__file__).parent / 'prompts' / f'stage{s}_system_v4.txt').read_text() for s in (1, 2)}
SCHEMAS = {1: Stage1Result.model_json_schema(), 2: Stage2Result.model_json_schema()}
SCHEMA_VERSION = 'judge-v2-contract-4'
CODE_SHA = digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))})


def fingerprint(config, registry):
    forced = config.run.decision_mode == class_mode.MODE
    return dict(implementation='judge-v2-4',
                code_sha256=CODE_SHA,
                parser=PARSER_VERSION, taxonomy=digest(TAXONOMY),
                policy=digest(class_mode.POLICY) if forced else registry.sha,
                policy_version=class_mode.VERSION if forced else registry.policy_version,
                prompts={s: digest(class_mode.PROMPTS[s] if forced else PROMPTS[s]) for s in (1, 2)},
                schemas={s: digest(class_mode.SCHEMA if forced and s == 2 else SCHEMAS[s]) for s in (1, 2)},
                decision_mode=config.run.decision_mode,
                guideline_sha256=digest(class_mode.GUIDELINE) if forced else None,
                inference=config.inference.model_dump(mode='json'),
                schema_version=class_mode.VERSION if forced else SCHEMA_VERSION)


def payload(stage, item, facts, registry, s1=None, decision_mode='rule_only'):
    common = {'command': item['command'], 'context': item.get('context', {})}
    if decision_mode == class_mode.MODE:
        common['decision_mode'] = decision_mode
    if stage == 1:
        return {**common, 'parser_facts': facts, 'taxonomy': TAXONOMY}
    if decision_mode == class_mode.MODE:
        return {**common, 'actions': [dict(action_id=f'a{i}', **a.model_dump(mode='json'))
                                      for i, a in enumerate(s1.actions, 1)],
                'class_policy_version': class_mode.VERSION,
                'guideline_class_definitions': class_mode.GUIDELINE['class_definitions'],
                'guideline_cards': class_mode.GUIDELINE['cards']}
    return {**common, 'actions': [dict(action_id=f'a{i}', **a.model_dump(mode='json'))
                                 for i, a in enumerate(s1.actions, 1)],
            'policy_version': registry.policy_version,
            'approved_rules_by_action': registry.compile(s1.actions)}


def system_prompt(stage, data):
    return class_mode.PROMPTS[stage] if data.get('decision_mode') == class_mode.MODE else PROMPTS[stage]


def schema(stage, data):
    return class_mode.SCHEMA if stage == 2 and data.get('decision_mode') == class_mode.MODE else SCHEMAS[stage]


def messages(stage, data, feedback=None):
    result = [{'role': 'system', 'content': system_prompt(stage, data)},
              {'role': 'user', 'content': dumps(data)}]
    if feedback:
        result.append({'role': 'user', 'content': 'Previous response failed validation: ' + feedback + '. Return a complete new JSON object.'})
    return result


def cache_key(stage, data, config, registry):
    f = fingerprint(config, registry)
    if stage == 1:
        f.pop('policy')
        f.pop('policy_version')
    f['prompts'] = f['prompts'][stage]
    f['schemas'] = f['schemas'][stage]
    return digest({'stage': stage, 'input': data, 'versions': f})


def validate(stage, content, data, registry):
    raw = json.loads(content)
    if stage == 1:
        return validate_stage1(raw, RISK_CODES).model_dump(mode='json')
    actions = [Stage1Result.model_validate({'actions': [{k: v for k, v in a.items() if k != 'action_id'}]}).actions[0]
               for a in data['actions']]
    if data.get('decision_mode') == class_mode.MODE:
        class_mode.materialize(raw, actions)
        return class_mode.ClassResult.model_validate(raw).model_dump(mode='json', by_alias=True)
    materialize(raw, actions, data['approved_rules_by_action'], registry)
    return Stage2Result.model_validate(raw).model_dump(mode='json')
