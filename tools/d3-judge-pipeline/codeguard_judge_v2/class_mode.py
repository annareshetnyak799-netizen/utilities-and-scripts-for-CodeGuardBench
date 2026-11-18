"""User-authorized guideline classification; no fabricated S055 rule matches."""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .schemas import ActionClass

DATA = Path(__file__).parent
GUIDELINE = json.loads((DATA / 'policy/guideline_cards.json').read_text())
PROMPTS = {
    1: (DATA / 'prompts/stage1_guideline_three_class_v1.txt').read_text(),
    2: (DATA / 'prompts/stage2_guideline_three_class_v3.txt').read_text(),
}
MODE = 'guideline_three_class'
VERSION = 'guideline-first-three-class-v3'


class ClassDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str = Field(pattern=r'^a[1-9][0-9]*$')
    action_class: ActionClass = Field(alias='class')
    note: str = Field(min_length=1, max_length=180)


class ClassResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decisions: list[ClassDecision] = Field(min_length=1, max_length=128)


SCHEMA = ClassResult.model_json_schema()
POLICY = {'version': VERSION, 'prompts': PROMPTS, 'guideline': GUIDELINE}


def materialize(raw, actions):
    result = ClassResult.model_validate(raw)
    expected = {f'a{i}': action for i, action in enumerate(actions, 1)}
    ids = [d.action_id for d in result.decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError('invalid_action_ids')
    return [dict(action_id=d.action_id, **{'class': d.action_class.value},
                 note=d.note, rule_id=None, review_reason=None,
                 risk=expected[d.action_id].risks[0] if expected[d.action_id].risks else None,
                 severity=None, classification_basis=VERSION)
            for d in sorted(result.decisions, key=lambda d: int(d.action_id[1:]))]
