import pytest
from pop_pay.core.models import GuardrailPolicy, PaymentIntent
from pop_pay.providers.stripe_mock import MockStripeProvider

@pytest.mark.asyncio
async def test_issue_card_success():
    provider = MockStripeProvider()
    
    intent = PaymentIntent(
        agent_id="agent-001",
        requested_amount=50.0,
        target_vendor="MockVendor",
        reasoning="Test"
    )
    
    policy = GuardrailPolicy(
        allowed_categories=["TEST"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    
    seal = await provider.issue_card(intent, policy)
    
    assert seal.status == "Issued"
    assert seal.card_number is not None
    # RT-2 R2 Fix 3 — SecretStr has no len(); reveal() gives the plaintext
    # for provider-roundtrip assertions.
    assert len(seal.card_number.reveal()) == 16
    assert seal.cvv is not None
    assert len(seal.cvv.reveal()) == 3
    assert seal.expiration_date is not None
    assert len(seal.expiration_date) == 5
    assert seal.authorized_amount == 50.0
    assert seal.rejection_reason is None

@pytest.mark.asyncio
async def test_issue_card_rejected():
    provider = MockStripeProvider()
    
    intent = PaymentIntent(
        agent_id="agent-002",
        requested_amount=150.0,
        target_vendor="MockVendor",
        reasoning="Test excess amount"
    )
    
    policy = GuardrailPolicy(
        allowed_categories=["TEST"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    
    seal = await provider.issue_card(intent, policy)
    
    assert seal.status == "Rejected"
    assert seal.authorized_amount == 0.0
    assert seal.rejection_reason is not None
    assert "Exceeds single transaction limit" in seal.rejection_reason
    assert seal.card_number is None
    assert seal.cvv is None
    assert seal.expiration_date is None
