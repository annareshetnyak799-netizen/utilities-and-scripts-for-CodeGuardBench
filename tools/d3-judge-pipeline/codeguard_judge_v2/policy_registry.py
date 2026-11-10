"""No implicit activation. Approval is an explicit, audited human operation."""
import json
from pathlib import Path
from typing import Literal
import yaml
from pydantic import Field, model_validator
from .common import digest, now, atomic_write, dumps
from .config import StrictModel
from .schemas import ActionClass, Severity, Stage2Result

DATA = Path(__file__).parent / 'policy'
TAXONOMY = json.loads((DATA / 'taxonomy_index.json').read_text())
RISK_CODES = {c['id'] for c in TAXONOMY['cards']}
assert len(RISK_CODES) == 42


class Approval(StrictModel):
    reviewer: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    rule_sha256: str = Field(pattern='^[a-f0-9]{64}$')


class Rule(StrictModel):
    id: str = Field(min_length=1)
    risk: str
    when: str = Field(min_length=1)
    exceptions: list[str]
    action_class: ActionClass = Field(alias='class')
    severity: Severity
    status: Literal['active', 'draft', 'conflicting', 'deprecated']
    source: dict[str, str]
    policy_version: str
    overrides: list[str] = Field(default_factory=list)
    exception_to: list[str] = Field(default_factory=list)
    approval: Approval | None = None

    def content_hash(self):
        return digest(self.model_dump(mode='json', by_alias=True, exclude={'approval', 'status', 'policy_version'}))

    @model_validator(mode='after')
    def valid(self):
        if self.risk not in RISK_CODES or not self.source.get('document') or not self.source.get('section'):
            raise ValueError('invalid taxonomy or missing rule provenance')
        if self.status == 'active' and (self.approval is None or self.approval.rule_sha256 != self.content_hash()):
            raise ValueError('active rule requires matching explicit approval')
        return self


class Registry(StrictModel):
    policy_version: str = Field(min_length=1)
    rules: list[Rule]
    audit: list[dict] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_registry(self):
        rules = {r.id: r for r in self.rules}
        if len(rules) != len(self.rules):
            raise ValueError('duplicate rule id')
        for r in self.rules:
            if r.policy_version != self.policy_version:
                raise ValueError('rule policy version mismatch')
            for ref in r.overrides + r.exception_to:
                if ref not in rules or ref == r.id or rules[ref].risk != r.risk:
                    raise ValueError('invalid rule relation')
                if r.status == 'active' and rules[ref].status != 'active':
                    raise ValueError('active exception requires active base rule')
        def visit(key, path):
            if key in path:
                raise ValueError('cyclic policy precedence')
            for ref in rules[key].overrides + rules[key].exception_to:
                visit(ref, path | {key})
        for r in self.rules:
            visit(r.id, set())
        active = [r for r in self.rules if r.status == 'active']
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if (a.risk, a.when, a.exceptions) == (b.risk, b.when, b.exceptions) and (a.action_class, a.severity) != (b.action_class, b.severity):
                    raise ValueError('conflicting identical active conditions')
        return self

    @property
    def sha(self):
        return digest(self.model_dump(mode='json', by_alias=True))

    def compile(self, actions):
        return {f'a{i}': [r.model_dump(mode='json', by_alias=True) for r in self.rules
                         if r.status == 'active' and r.risk in a.risks]
                for i, a in enumerate(actions, 1)}

    def gaps(self):
        covered = {r.risk for r in self.rules if r.status == 'active'}
        return {'policy_version': self.policy_version, 'sha256': self.sha,
                'active_rules': sum(r.status == 'active' for r in self.rules),
                'risks_without_active_rules': sorted(RISK_CODES - covered),
                'issues': yaml.safe_load((DATA / 'issues.yaml').read_text())['issues']}


def load_registry(path=None):
    data = yaml.safe_load(Path(path or DATA / 'registry_example.yaml').read_text())
    # The reference omits per-rule versions. Inherit explicitly, without changing status.
    for r in data['rules']:
        r.setdefault('policy_version', data['policy_version'])
    return Registry.model_validate(data)


def approve(path, output, ids, reviewer, evidence, version):
    reg = load_registry(path)
    if version == reg.policy_version:
        raise ValueError('approval requires a new policy version')
    if not set(ids) <= {r.id for r in reg.rules}:
        raise ValueError('unknown approval rule id')
    previous = reg.sha
    for r in reg.rules:
        r.policy_version = version
        if r.id in ids:
            if r.status != 'draft':
                raise ValueError('only reviewed draft rules can be approved')
            r.approval = Approval(reviewer=reviewer, approved_at=now(), evidence=evidence, rule_sha256=r.content_hash())
            r.status = 'active'
    reg.policy_version = version
    reg.audit.append(dict(event='human_policy_approval', reviewer=reviewer, evidence=evidence,
                          at=now(), rule_ids=ids, previous_sha256=previous))
    reg = Registry.model_validate(reg.model_dump(mode='json', by_alias=True))
    atomic_write(output, dumps(reg.model_dump(mode='json', by_alias=True)) + '\n')
    return reg


def materialize(raw, actions, offered, registry):
    result = Stage2Result.model_validate(raw)
    indexed = {f'a{i}': a for i, a in enumerate(actions, 1)}
    ids = [d.action_id for d in result.decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(indexed):
        raise ValueError('invalid_action_ids')
    rules = {r.id: r for r in registry.rules}
    output = []
    for d in result.decisions:
        a = indexed[d.action_id]
        row = d.model_dump(mode='json')
        if d.rule_id is not None:
            r = rules.get(d.rule_id)
            if (r is None or r.status != 'active' or r.policy_version != registry.policy_version
                or r.risk not in a.risks or d.rule_id not in {x['id'] for x in offered[d.action_id]}):
                raise ValueError('invalid_rule_ref')
            # Unresolved context does not automatically invalidate a visible risk.
            # Stage 2 may choose an active rule covering the attempted mechanism
            # regardless of an unknown payload/target. Missing essential context
            # is reported by Stage 2 through review_reason, not guessed here.
            if r.risk != a.risks[0]:
                row.update(rule_id=None, review_reason='semantic_mismatch')
            else:
                row.update(risk=r.risk, **{'class': r.action_class.value}, severity=r.severity.value)
        output.append(row)
    return sorted(output, key=lambda r: int(r['action_id'][1:]))
