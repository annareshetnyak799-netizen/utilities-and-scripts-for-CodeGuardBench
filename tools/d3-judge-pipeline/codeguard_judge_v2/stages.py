import json
from pathlib import Path
from .common import digest, dumps
from .parser import PARSER_VERSION
from .policy_registry import TAXONOMY, RISK_CODES, materialize
from .schemas import Stage1Result, Stage2Result, validate_stage1

# v0 scope: only CAT-0..6, selected from the full versioned taxonomy.
V0_TAXONOMY = {**TAXONOMY, 'cards': [c for c in TAXONOMY['cards']
                if int(c['id'].split('-')[1].split('.')[0]) <= 6]}
V0_RISK_CODES = {c['id'] for c in V0_TAXONOMY['cards']}
assert len(V0_RISK_CODES) == 30

PROMPTS = {s: (Path(__file__).parent / 'prompts' / f'stage{s}_system_v2.txt').read_text() for s in (1, 2)}
SCHEMAS = {1: Stage1Result.model_json_schema(), 2: Stage2Result.model_json_schema()}
SCHEMA_VERSION = 'judge-v2-contract-2'
CODE_SHA = digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))})


def fingerprint(config, registry):
    return dict(implementation='judge-v2-2',
                code_sha256=CODE_SHA,
                parser=PARSER_VERSION, taxonomy=digest(V0_TAXONOMY),
                policy=registry.sha, policy_version=registry.policy_version,
                prompts={s: digest(PROMPTS[s]) for s in (1, 2)},
                schemas={s: digest(SCHEMAS[s]) for s in (1, 2)},
                inference=config.inference.model_dump(mode='json'), schema_version=SCHEMA_VERSION)


def payload(stage, item, facts, registry, s1=None):
    common = {'command': item['command'], 'context': item.get('context', {})}
    if stage == 1:
        return {**common, 'parser_facts': facts, 'taxonomy': V0_TAXONOMY}
    return {**common, 'actions': [dict(action_id=f'a{i}', **a.model_dump(mode='json'))
                                 for i, a in enumerate(s1.actions, 1)],
            'policy_version': registry.policy_version,
            'approved_rules_by_action': registry.compile(s1.actions)}


def messages(stage, data, feedback=None):
    result = [{'role': 'system', 'content': PROMPTS[stage]},
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
        return validate_stage1(raw, V0_RISK_CODES).model_dump(mode='json')
    actions = [Stage1Result.model_validate({'actions': [{k: v for k, v in a.items() if k != 'action_id'}]}).actions[0]
               for a in data['actions']]
    materialize(raw, actions, data['approved_rules_by_action'], registry)
    return Stage2Result.model_validate(raw).model_dump(mode='json')
