import pytest
from pop_pay.core.models import GuardrailPolicy, PaymentIntent, VirtualSeal
from pop_pay.core.secret_str import SecretStr

def test_guardrail_policy():
    policy = GuardrailPolicy(
        allowed_categories=["API_SERVICES", "SUBSCRIPTIONS"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
        block_hallucination_loops=True
    )
    assert policy.max_amount_per_tx == 50.0
    assert "API_SERVICES" in policy.allowed_categories

def test_payment_intent():
    intent = PaymentIntent(
        agent_id="agent-007",
        requested_amount=19.99,
        target_vendor="OpenAI API",
        reasoning="To perform data analysis"
    )
    assert intent.agent_id == "agent-007"
    assert intent.requested_amount == 19.99

def test_virtual_seal():
    seal = VirtualSeal(
        seal_id="seal-12345",
        card_number=SecretStr("1234567812345678"),
        authorized_amount=19.99,
        status="Issued"
    )
    assert seal.status == "Issued"
    assert seal.authorized_amount == 19.99
    # RT-2 R2 Fix 3 — PAN is opaque; only last4 projection is public.
    assert seal.card_number.last4() == "5678"
    assert str(seal.card_number) == "***REDACTED***"
