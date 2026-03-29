"""
Smoke tests for all renamed classes in the pop_pay package.
Verifies imports, instantiation, and basic operations without real network calls.
"""
import pytest

# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_import_pop_client():
    from pop_pay.client import PopClient
    assert PopClient is not None


def test_import_pop_browser_injector():
    from pop_pay.injector import PopBrowserInjector
    assert PopBrowserInjector is not None


def test_import_pop_state_tracker():
    from pop_pay.core.state import PopStateTracker
    assert PopStateTracker is not None


def test_import_pop_payment_tool_and_input():
    from pop_pay.tools.langchain import PopPaymentTool, PopPaymentInput
    assert PopPaymentTool is not None
    assert PopPaymentInput is not None


def test_import_mcp_server():
    """mcp_server module should import without errors."""
    import importlib
    spec = importlib.util.find_spec("pop_pay.mcp_server")
    assert spec is not None, "pop_pay.mcp_server module not found"
    # Actually import to verify no import-time exceptions
    mod = importlib.import_module("pop_pay.mcp_server")
    assert mod is not None


# ---------------------------------------------------------------------------
# PopStateTracker — instantiation and basic operations
# ---------------------------------------------------------------------------

def test_pop_state_tracker_instantiation():
    from pop_pay.core.state import PopStateTracker
    tracker = PopStateTracker(db_path=":memory:")
    assert tracker is not None
    tracker.close()


def test_pop_state_tracker_record_seal():
    from pop_pay.core.state import PopStateTracker
    tracker = PopStateTracker(db_path=":memory:")
    tracker.record_seal("seal-001", 25.0, "TestVendor", status="Issued")
    details = tracker.get_seal_details("seal-001")
    assert isinstance(details, dict)
    tracker.close()


def test_pop_state_tracker_can_spend():
    from pop_pay.core.state import PopStateTracker
    tracker = PopStateTracker(db_path=":memory:")
    # Nothing spent yet — should be able to spend within budget
    assert tracker.can_spend(50.0, 100.0) is True
    # Amount over budget should return False
    assert tracker.can_spend(200.0, 100.0) is False
    tracker.close()


def test_pop_state_tracker_mark_used():
    from pop_pay.core.state import PopStateTracker
    tracker = PopStateTracker(db_path=":memory:")
    tracker.record_seal("seal-002", 10.0, "Vendor", status="Issued")
    assert tracker.is_used("seal-002") is False
    tracker.mark_used("seal-002")
    assert tracker.is_used("seal-002") is True
    tracker.close()


# ---------------------------------------------------------------------------
# PopClient — instantiation and process_payment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pop_client_instantiation():
    from pop_pay.client import PopClient
    from pop_pay.providers.stripe_mock import MockStripeProvider
    from pop_pay.core.models import GuardrailPolicy

    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["aws", "openai"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True,
    )
    client = PopClient(provider=provider, policy=policy, db_path=":memory:")
    assert client is not None
    client.state_tracker.close()


@pytest.mark.asyncio
async def test_pop_client_process_payment_approved():
    from pop_pay.client import PopClient
    from pop_pay.providers.stripe_mock import MockStripeProvider
    from pop_pay.core.models import GuardrailPolicy, PaymentIntent

    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["aws", "openai"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True,
    )
    client = PopClient(provider=provider, policy=policy, db_path=":memory:")

    intent = PaymentIntent(
        agent_id="test-agent",
        requested_amount=20.0,
        target_vendor="AWS Compute",
        reasoning="Provisioning cloud resources for data pipeline.",
    )
    seal = await client.process_payment(intent)
    assert seal is not None
    assert seal.seal_id
    # MockStripeProvider always approves within-budget, within-limit requests
    assert seal.status in ("Issued", "Rejected")
    client.state_tracker.close()


@pytest.mark.asyncio
async def test_pop_client_process_payment_budget_exceeded():
    from pop_pay.client import PopClient
    from pop_pay.providers.stripe_mock import MockStripeProvider
    from pop_pay.core.models import GuardrailPolicy, PaymentIntent

    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["aws"],
        max_amount_per_tx=100.0,
        max_daily_budget=10.0,  # very low daily budget
        block_hallucination_loops=True,
    )
    client = PopClient(provider=provider, policy=policy, db_path=":memory:")

    intent = PaymentIntent(
        agent_id="test-agent",
        requested_amount=50.0,  # exceeds daily budget
        target_vendor="AWS",
        reasoning="Buying more compute.",
    )
    seal = await client.process_payment(intent)
    assert seal.status == "Rejected"
    assert seal.rejection_reason == "Daily budget exceeded"
    client.state_tracker.close()


# ---------------------------------------------------------------------------
# PopPaymentTool — instantiation
# ---------------------------------------------------------------------------

def test_pop_payment_tool_instantiation():
    from pop_pay.client import PopClient
    from pop_pay.providers.stripe_mock import MockStripeProvider
    from pop_pay.core.models import GuardrailPolicy
    from pop_pay.tools.langchain import PopPaymentTool

    provider = MockStripeProvider()
    policy = GuardrailPolicy(
        allowed_categories=["aws"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True,
    )
    client = PopClient(provider=provider, policy=policy, db_path=":memory:")
    tool = PopPaymentTool(client=client, agent_id="smoke-agent")
    assert tool is not None
    assert tool.name == "pop_payment_tool"
    assert tool.agent_id == "smoke-agent"
    client.state_tracker.close()


def test_pop_payment_input_schema():
    from pop_pay.tools.langchain import PopPaymentInput

    inp = PopPaymentInput(
        requested_amount=15.0,
        target_vendor="OpenAI",
        reasoning="API usage for inference.",
    )
    assert inp.requested_amount == 15.0
    assert inp.target_vendor == "OpenAI"


# ---------------------------------------------------------------------------
# PopBrowserInjector — instantiation (no real browser required)
# ---------------------------------------------------------------------------

def test_pop_browser_injector_instantiation():
    from pop_pay.injector import PopBrowserInjector
    from pop_pay.core.state import PopStateTracker

    tracker = PopStateTracker(db_path=":memory:")
    injector = PopBrowserInjector(state_tracker=tracker)
    assert injector is not None
    assert injector.state_tracker is tracker
    tracker.close()
