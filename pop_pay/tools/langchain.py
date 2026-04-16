import os
from typing import Type, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from pop_pay.core.models import PaymentIntent
from pop_pay.client import PopClient


class PopPaymentInput(BaseModel):
    requested_amount: float = Field(..., description="The amount of money to request.")
    target_vendor: str = Field(..., description="The vendor to pay.")
    reasoning: str = Field(..., description="Reasoning for this payment.")
    page_url: str = Field(default="", description="Current checkout page URL. Pass this when using Playwright MCP to enable TOCTOU domain validation.")


class PopPaymentTool(BaseTool):
    name: str = "pop_payment_tool"
    description: str = (
        "Use this tool to request a one-time virtual card for an automated purchase. "
        "ONLY call this tool when you are on the FINAL checkout page and can visually "
        "confirm that credit card input fields are visible. "
        "If auto-injection is enabled, the card will be securely filled into the browser "
        "automatically — you only need to click the submit/pay button afterward. "
        "DO NOT retry with different reasoning if rejected. "
        "Provide the amount (float), target vendor (str), and your full reasoning (str)."
    )
    args_schema: Type[BaseModel] = PopPaymentInput

    client: Any = Field(description="The PopClient instance")
    agent_id: str = Field(..., description="The ID of the Agent making the request")
    injector: Optional[Any] = Field(default=None, description="Optional PopBrowserInjector instance")
    cdp_url: str = Field(default="http://localhost:9222", description="CDP endpoint for browser injection")

    def __init__(
        self,
        client: PopClient,
        agent_id: str,
        injector=None,
        cdp_url: str = "http://localhost:9222",
        **kwargs,
    ):
        super().__init__(
            client=client,
            agent_id=agent_id,
            injector=injector,
            cdp_url=cdp_url,
            **kwargs,
        )

    def _run(
        self,
        requested_amount: float,
        target_vendor: str,
        reasoning: str,
        page_url: str = "",
        run_manager=None,
    ) -> str:
        return "Please use the async method ainvoke() for PopPaymentTool."

    async def _arun(
        self,
        requested_amount: float,
        target_vendor: str,
        reasoning: str,
        page_url: str = "",
        run_manager=None,
    ) -> str:
        intent = PaymentIntent(
            agent_id=self.agent_id,
            requested_amount=requested_amount,
            target_vendor=target_vendor,
            reasoning=reasoning,
        )

        seal = await self.client.process_payment(intent)

        if seal.status.lower() == "rejected":
            return f"Payment rejected by guardrails. Reason: {seal.rejection_reason}"

        # RT-2 R2 Fix 3: SecretStr.last4() returns the last 4 chars. For
        # Stripe Issuing this produces "****-****-****-1234" from the pre-masked
        # "****1234" value (last4("****1234") == "1234"), uniform with BYOC/mock
        # that carry a full 16-digit PAN.
        if seal.card_number:
            masked_card = f"****-****-****-{seal.card_number.last4()}"
        else:
            masked_card = "****-****-****-????"

        # -------------------------------------------------------------------
        # Auto-injection path: if an injector is provided, fill the browser
        # -------------------------------------------------------------------
        if self.injector is not None:
            injection_result = await self.injector.inject_payment_info(
                seal_id=seal.seal_id,
                cdp_url=self.cdp_url,
                card_number=seal.card_number or "",
                cvv=seal.cvv or "",
                expiration_date=seal.expiration_date or "",
                page_url=page_url,
                approved_vendor=target_vendor,
            )

            if isinstance(injection_result, dict):
                card_filled = injection_result.get("card_filled", False)
            else:
                card_filled = bool(injection_result)

            if not card_filled:
                # Cancel the budget reservation — treat as if never issued
                self.client.state_tracker.mark_used(seal.seal_id)
                return (
                    "Payment rejected. Error: Point One Percent could not find credit card input "
                    "fields on your active browser tab. Please ensure you have navigated "
                    "to the FINAL checkout form and the card fields are visible, then retry."
                )

            return (
                f"Payment approved and securely auto-injected into the browser form. "
                f"Please proceed to click the submit/pay button. "
                f"Masked card: {masked_card}"
            )

        # -------------------------------------------------------------------
        # Standard path: return masked card details only
        # -------------------------------------------------------------------
        return (
            f"Payment approved. Card Issued: {masked_card}, "
            f"Expiry: {seal.expiration_date}, Authorized Amount: {seal.authorized_amount}"
        )
