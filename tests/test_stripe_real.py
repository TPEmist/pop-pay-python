import pytest
from unittest.mock import MagicMock, patch
from pop_pay.core.models import GuardrailPolicy, PaymentIntent, VirtualSeal
from pop_pay.providers.stripe_real import StripeIssuingProvider
import stripe

@pytest.fixture
def provider():
    return StripeIssuingProvider(api_key="sk_test_123")

@pytest.mark.asyncio
async def test_issue_card_success(provider):
    intent = PaymentIntent(
        agent_id="agent-001",
        requested_amount=50.0,
        target_vendor="RealVendor",
        reasoning="Test"
    )
    
    policy = GuardrailPolicy(
        allowed_categories=["TEST"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    
    with patch("stripe.issuing.Cardholder.create") as mock_ch_create, \
         patch("stripe.issuing.Card.create") as mock_card_create:
        
        # Setup mocks
        mock_cardholder = MagicMock()
        mock_cardholder.id = "ich_123"
        mock_ch_create.return_value = mock_cardholder
        
        mock_card = MagicMock()
        mock_card.last4 = "4242"
        mock_card.exp_month = 12
        mock_card.exp_year = 2026
        mock_card_create.return_value = mock_card
        
        seal = await provider.issue_card(intent, policy)
        
        # Verify cardholder creation
        mock_ch_create.assert_called_once_with(
            type='individual',
            name='POP Agent',
            billing={
                'address': {
                    'line1': '123 AI St',
                    'city': 'San Francisco',
                    'state': 'CA',
                    'postal_code': '94105',
                    'country': 'US'
                }
            }
        )
        
        # Verify card creation
        mock_card_create.assert_called_once_with(
            cardholder="ich_123",
            type='virtual',
            currency='usd',
            spending_controls={
                'spending_limits': [
                    {
                        'amount': 5000,
                        'interval': 'all_time'
                    }
                ]
            }
        )
        
        assert seal.status == "Issued"
        # RT-2 R2 Fix 3 — PAN/CVV wrapped in SecretStr; compare via .reveal().
        assert seal.card_number.reveal() == "****4242"
        assert seal.cvv.reveal() == "***"
        assert seal.expiration_date == "12/2026"
        assert seal.authorized_amount == 50.0

@pytest.mark.asyncio
async def test_issue_card_stripe_error(provider):
    intent = PaymentIntent(
        agent_id="agent-001",
        requested_amount=50.0,
        target_vendor="RealVendor",
        reasoning="Test"
    )
    
    policy = GuardrailPolicy(
        allowed_categories=["TEST"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    
    with patch("stripe.issuing.Cardholder.create") as mock_ch_create:
        mock_ch_create.side_effect = stripe.StripeError("Stripe broke")
        
        seal = await provider.issue_card(intent, policy)
        
        assert seal.status == "Rejected"
        assert seal.authorized_amount == 0.0
        assert seal.rejection_reason == "Stripe broke"

@pytest.mark.asyncio
async def test_issue_card_general_exception(provider):
    intent = PaymentIntent(
        agent_id="agent-001",
        requested_amount=50.0,
        target_vendor="RealVendor",
        reasoning="Test"
    )
    
    policy = GuardrailPolicy(
        allowed_categories=["TEST"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    
    with patch("stripe.issuing.Cardholder.create") as mock_ch_create:
        mock_ch_create.side_effect = Exception("General error")
        
        seal = await provider.issue_card(intent, policy)
        
        assert seal.status == "Rejected"
        assert seal.authorized_amount == 0.0
        assert seal.rejection_reason == "General error"
