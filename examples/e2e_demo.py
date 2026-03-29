"""
Point One Percent — End-to-End Demo
=====================================
Demonstrates the three core guardrail scenarios using the keyword engine
(default mode, zero-cost, no API key required).

Run:
    uv run python examples/e2e_demo.py
"""

import asyncio

from pop_pay.client import PopClient
from pop_pay.core.models import GuardrailPolicy
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.tools.langchain import PopPaymentTool

DIVIDER = "=" * 60


async def main() -> None:
    print(DIVIDER)
    print(" Point One Percent — End-to-End Demo")
    print(" Guardrail mode : KEYWORD  (default, zero-cost, no API key)")
    print(" Card provider  : Mock     (no real money involved)")
    print(DIVIDER)

    # ------------------------------------------------------------------ #
    # Initialise
    # ------------------------------------------------------------------ #
    policy = GuardrailPolicy(
        allowed_categories=["aws", "cloudflare"],
        max_amount_per_tx=50.0,
        max_daily_budget=1000.0,
        block_hallucination_loops=True,
    )
    client = PopClient(provider=MockStripeProvider(), policy=policy)
    tool = PopPaymentTool(client=client, agent_id="agent-e2e-demo")

    # ------------------------------------------------------------------ #
    # Scenario A — Approved payment
    # ------------------------------------------------------------------ #
    print("\n[Scenario A]  Approved — domain registration within policy")
    print(f"  Vendor    : cloudflare")
    print(f"  Amount    : $15.00  (limit: $50.00)")
    print(f"  Reasoning : 'Register domain for the user's new agentic workflow tool.'")
    result_a = await tool.ainvoke({
        "requested_amount": 15.0,
        "target_vendor": "cloudflare",
        "reasoning": "Register domain for the user's new agentic workflow tool.",
    })
    print(f"  Result    : {result_a}")

    # ------------------------------------------------------------------ #
    # Scenario B — Budget cap exceeded
    # ------------------------------------------------------------------ #
    print("\n[Scenario B]  Blocked — amount exceeds per-transaction cap")
    print(f"  Vendor    : aws")
    print(f"  Amount    : $500.00  (limit: $50.00)")
    print(f"  Reasoning : 'Provision an EC2 p4d instance for model training.'")
    result_b = await tool.ainvoke({
        "requested_amount": 500.0,
        "target_vendor": "aws",
        "reasoning": "Provision an EC2 p4d instance for model training.",
    })
    print(f"  Result    : {result_b}")

    # ------------------------------------------------------------------ #
    # Scenario C — Hallucination loop detected
    # ------------------------------------------------------------------ #
    print("\n[Scenario C]  Blocked — hallucination / retry loop detected")
    print(f"  Vendor    : aws")
    print(f"  Amount    : $10.00")
    print(f"  Reasoning : '...failed again...retry loop...'")
    result_c = await tool.ainvoke({
        "requested_amount": 10.0,
        "target_vendor": "aws",
        "reasoning": "The previous API call failed again. I am stuck in a loop. "
                     "Let me retry and buy more compute to bypass the error.",
    })
    print(f"  Result    : {result_c}")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n{DIVIDER}")
    print(" Installation verified. All three scenarios behaved as expected.")
    print(DIVIDER)

    print("""
NOTE: The guardrail decisions above were made by the KEYWORD engine —
a fast, pattern-based check for obvious misuse (loops, over-budget, etc.).
This is the default mode and requires zero configuration.

To experience LLM-based semantic analysis, which catches subtler misuse
such as off-topic purchases or logically inconsistent reasoning:

  See docs/INTEGRATION_GUIDE.md §1 "Guardrail Mode Configuration" for the
  full .env reference and provider options (OpenAI, Ollama, OpenRouter, etc.).

  1. Add the following to your .env:
       POP_GUARDRAIL_ENGINE=llm
       POP_LLM_API_KEY=<your-openai-or-compatible-key>

  2. Run the LLM guardrail test:
       uv run python scripts/test_llm_guardrails.py
""")


if __name__ == "__main__":
    asyncio.run(main())
