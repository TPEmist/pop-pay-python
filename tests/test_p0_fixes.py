import pytest
import uuid
from pop_pay.client import PopClient
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal
from pop_pay.core.secret_str import SecretStr
from pop_pay.providers.base import VirtualCardProvider

class MockProvider(VirtualCardProvider):
    async def issue_card(self, intent: PaymentIntent, policy: GuardrailPolicy) -> VirtualSeal:
        return VirtualSeal(
            seal_id=str(uuid.uuid4()),
            card_number=SecretStr("1234567812345678"),
            cvv=SecretStr("123"),
            expiration_date="12/26",
            authorized_amount=intent.requested_amount,
            status="Issued"
        )

@pytest.mark.asyncio
async def test_daily_budget_enforcement():
    policy = GuardrailPolicy(
        allowed_categories=["cloud"],
        max_amount_per_tx=100.0,
        max_daily_budget=150.0,
        block_hallucination_loops=True
    )
    client = PopClient(MockProvider(), policy, db_path=":memory:")
    
    intent = PaymentIntent(agent_id="test", requested_amount=100.0, target_vendor="cloud", reasoning="test")
    
    # First payment: OK
    seal1 = await client.process_payment(intent)
    assert seal1.status == "Pending"
    assert client.state_tracker.daily_spend_total == 100.0
    
    # Second payment: Should exceed budget (100 + 100 > 150)
    seal2 = await client.process_payment(intent)
    assert seal2.status == "Rejected"
    assert seal2.rejection_reason == "Daily budget exceeded"
    assert client.state_tracker.daily_spend_total == 100.0

@pytest.mark.asyncio
async def test_burn_after_use_enforcement():
    policy = GuardrailPolicy(
        allowed_categories=["cloud"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    client = PopClient(MockProvider(), policy, db_path=":memory:")
    
    intent = PaymentIntent(agent_id="test", requested_amount=50.0, target_vendor="cloud", reasoning="test")
    seal = await client.process_payment(intent)
    
    # First execution: OK
    res1 = await client.execute_payment(seal.seal_id, 50.0)
    assert res1["status"] == "success"
    
    # Second execution: Should be rejected
    res2 = await client.execute_payment(seal.seal_id, 50.0)
    assert res2["status"] == "rejected"
    assert res2["reason"] == "Burn-after-use enforced"

@pytest.mark.asyncio
async def test_card_masking_langchain():
    from pop_pay.tools.langchain import PopPaymentTool
    from pop_pay.core.models import VirtualSeal
    
    policy = GuardrailPolicy(
        allowed_categories=["cloud"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True
    )
    client = PopClient(MockProvider(), policy, db_path=":memory:")
    tool = PopPaymentTool(client=client, agent_id="agent-1")
    
    result = await tool._arun(requested_amount=50.0, target_vendor="cloud", reasoning="Buying some compute")
    
    assert "****-****-****-5678" in result
    assert "CVV" not in result
    assert "123" not in result
