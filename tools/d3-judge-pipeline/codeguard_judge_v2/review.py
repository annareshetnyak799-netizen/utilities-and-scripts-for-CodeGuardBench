"""Explicit import of human decisions, never an automatic approval path."""
from datetime import datetime
from pydantic import Field, model_validator
from .config import StrictModel
from .common import digest, dumps
from .schemas import ActionClass, Severity
from .policy_registry import RISK_CODES


class HumanDecision(StrictModel):
    id: str
    command_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    policy_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=1)
    adjudicated_at: datetime
    evidence: str = Field(min_length=1)
    independent: bool
    primary_risk: str
    proposed_final_class: ActionClass
    severity: Severity
    rule_id: str
    description: str = Field(min_length=1)

    @model_validator(mode='after')
    def valid(self):
        if not self.independent or self.primary_risk not in RISK_CODES:
            raise ValueError('independent human adjudication and valid taxonomy required')
        return self


def import_decisions(store, run, registry, rows):
    rules = {r.id: r for r in registry.rules if r.status == 'active'}
    count = 0
    seen = set()
    with store.db:
        for raw in rows:
            h = HumanDecision.model_validate(raw)
            if h.id in seen:
                raise ValueError('duplicate human review id')
            seen.add(h.id)
            row = store.db.execute('SELECT body FROM inputs WHERE run_id=? AND input_id=?', (run, h.id)).fetchone()
            import json
            if row is None or digest(json.loads(row[0])['command']) != h.command_sha256 or h.policy_sha256 != registry.sha:
                raise ValueError('human review command/policy mismatch')
            rule = rules.get(h.rule_id)
            if not rule or (rule.risk, rule.action_class, rule.severity) != (h.primary_risk, h.proposed_final_class, h.severity):
                raise ValueError('human review requires an active matching atomic rule')
            store.db.execute('INSERT INTO human_reviews VALUES(?,?,?)', (run, h.id, dumps(h.model_dump(mode='json'))))
            count += 1
    store.event(run, 'human_review_import', {'count': count})
    return {'human_decisions_imported': count}
