"""
test_v03_features.py — Tests for v0.3.0 features:
  - AegisClient engine injection
  - LLMGuardrailEngine configuration
  - MCP server environment variable logic
  - AegisBrowserInjector unit tests (no real browser required)
  - AegisPaymentTool with injector feedback loop
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.client import AegisClient
from aegis.engine.guardrails import GuardrailEngine
from aegis.engine.llm_guardrails import LLMGuardrailEngine
from aegis.core.models import GuardrailPolicy, PaymentIntent
from aegis.providers.stripe_mock import MockStripeProvider


# ---------------------------------------------------------------------------
# SDK: Engine dependency injection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_engine_injection():
    policy = GuardrailPolicy(allowed_categories=["test"], max_amount_per_tx=10, max_daily_budget=100)
    provider = MockStripeProvider()

    # Default engine
    client_default = AegisClient(provider, policy, db_path=":memory:")
    assert isinstance(client_default.engine, GuardrailEngine)

    # Injected engine
    custom_engine = GuardrailEngine()
    client_custom = AegisClient(provider, policy, engine=custom_engine, db_path=":memory:")
    assert client_custom.engine is custom_engine


# ---------------------------------------------------------------------------
# SDK: LLMGuardrailEngine configuration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_llm_engine_config():
    engine = LLMGuardrailEngine(
        api_key="sk-test",
        base_url="https://api.ollama.com/v1",
        model="llama3",
        use_json_mode=False,
    )
    assert engine.client.api_key == "sk-test"
    assert str(engine.client.base_url) == "https://api.ollama.com/v1/"
    assert engine.model == "llama3"
    assert engine.use_json_mode is False


# ---------------------------------------------------------------------------
# MCP server: environment variable logic
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mcp_server_env_logic(monkeypatch):
    import json
    monkeypatch.setenv("AEGIS_ALLOWED_CATEGORIES", '["openai", "anthropic"]')
    monkeypatch.setenv("AEGIS_MAX_PER_TX", "250.0")
    monkeypatch.setenv("AEGIS_AUTO_INJECT", "false")

    import importlib
    import aegis.mcp_server
    importlib.reload(aegis.mcp_server)

    assert aegis.mcp_server.policy.allowed_categories == ["openai", "anthropic"]
    assert aegis.mcp_server.policy.max_amount_per_tx == 250.0
    assert aegis.mcp_server.injector is None  # auto_inject=false


# ---------------------------------------------------------------------------
# Injector: no-fields → returns False (mocked browser)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_injector_no_fields_returns_false():
    from aegis.injector import AegisBrowserInjector
    from aegis.core.state import AegisStateTracker

    tracker = AegisStateTracker(db_path=":memory:")
    # Insert a fake seal with card details
    tracker.record_seal("seal-abc", 10.0, "test", "Issued", "4111111111111111", "123", "12/28")

    injector = AegisBrowserInjector(tracker)

    # Mock playwright to simulate "no card fields found" on any frame
    mock_frame = MagicMock()
    mock_frame.url = "https://example.com"
    mock_frame.locator.return_value.first.count = AsyncMock(return_value=0)

    mock_page = MagicMock()
    mock_page.frames = [mock_frame]
    mock_page.bring_to_front = AsyncMock()

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    class MockPlaywrightCtx:
        async def __aenter__(self):
            return mock_pw
        async def __aexit__(self, *args):
            pass

    import sys
    from unittest.mock import patch

    # Mock playwright at the system level since it's an optional dependency
    mock_playwright_module = MagicMock()
    mock_playwright_module.async_api.async_playwright = MagicMock(return_value=MockPlaywrightCtx())
    
    with patch.dict("sys.modules", {"playwright": mock_playwright_module, "playwright.async_api": mock_playwright_module.async_api}):
        # Need to import inside patch context
        from aegis.injector import AegisBrowserInjector as Inj
        inj = Inj(tracker)
        result = await inj.inject_payment_info("seal-abc")

    assert result == {"card_filled": False, "billing_filled": False}
    tracker.close()


# ---------------------------------------------------------------------------
# LangChain Tool: injector failure → feedback message + seal marked used
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_langchain_tool_injector_failure_feedback():
    from aegis.tools.langchain import AegisPaymentTool

    policy = GuardrailPolicy(
        allowed_categories=["cloud"],
        max_amount_per_tx=100.0,
        max_daily_budget=500.0,
        block_hallucination_loops=True,
    )
    client = AegisClient(MockStripeProvider(), policy, db_path=":memory:")

    # Mock injector that always fails
    mock_injector = MagicMock()
    mock_injector.inject_payment_info = AsyncMock(return_value=False)

    tool = AegisPaymentTool(client=client, agent_id="test-agent", injector=mock_injector)
    result = await tool._arun(
        requested_amount=50.0,
        target_vendor="cloud",
        reasoning="Testing injector failure path",
    )

    assert "could not find credit card input fields" in result.lower()
    assert "retry" in result.lower()
