import pytest
from codeguard_judge_v2.policy_registry import load_registry, Registry, Approval


@pytest.fixture
def active_registry():
    # Test-only signers. Never saved as production policy or used in actual runs.
    registry = load_registry()
    for rule in registry.rules:
        rule.approval = Approval(reviewer='TEST_FIXTURE_NOT_HUMAN_SIGNOFF', approved_at='2026-11-09T00:00:00Z',
                                 evidence='test fixture only', rule_sha256=rule.content_hash())
        rule.status = 'active'
    return Registry.model_validate(registry.model_dump(mode='json', by_alias=True))
