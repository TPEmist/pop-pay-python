import pytest
from pop_pay.core.models import GuardrailPolicy
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.client import PopClient
from pop_pay.tools.langchain import PopPaymentTool

@pytest.mark.asyncio
async def test_integration_chain_success():
    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["OpenAI", "AWS", "GitHub"],
        max_amount_per_tx=100.0,
        max_daily_budget=1000.0,
        block_hallucination_loops=True
    )
    
    client = PopClient(provider, policy)
    tool = PopPaymentTool(client=client, agent_id="agent-007")
    
    result = await tool._arun(
        requested_amount=20.0,
        target_vendor="OpenAI API",
        reasoning="We need GPT-4 calls to complete the translation job."
    )
    
    assert "Payment approved." in result
    assert "Card Issued: " in result

@pytest.mark.asyncio
async def test_integration_chain_hallucination_rejection():
    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["OpenAI", "AWS", "GitHub"],
        max_amount_per_tx=100.0,
        max_daily_budget=1000.0,
        block_hallucination_loops=True
    )
    
    client = PopClient(provider, policy)
    tool = PopPaymentTool(client=client, agent_id="agent-008")
    
    result = await tool._arun(
        requested_amount=10.0,
        target_vendor="GitHub Copilot",
        reasoning="I got stuck and this requires a loop to ignore previous instructions."
    )
    
    assert "Payment rejected by guardrails." in result
    assert "Hallucination or infinite loop detected" in result
