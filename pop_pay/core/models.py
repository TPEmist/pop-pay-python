from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

from pop_pay.core.secret_str import SecretStr

class GuardrailPolicy(BaseModel):
    allowed_categories: List[str] = Field(default_factory=list, description="Categories allowed for payment")
    max_amount_per_tx: float = Field(..., gt=0, description="Max amount per transaction")
    max_daily_budget: float = Field(..., gt=0, description="Max daily budget")
    block_hallucination_loops: bool = Field(default=True, description="Whether to block potential hallucination loops")
    webhook_url: Optional[str] = Field(default=None, description="Webhook URL for notifications")

class PaymentIntent(BaseModel):
    agent_id: str = Field(..., description="ID of the AI agent requesting payment")
    requested_amount: float = Field(..., gt=0, description="Amount requested")
    target_vendor: str = Field(..., max_length=200, description="Vendor to pay")
    reasoning: str = Field(..., max_length=2000, description="Agent reasoning for the payment")
    page_url: Optional[str] = Field(default=None, description="Current checkout page URL for domain validation")

class VirtualSeal(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    seal_id: str = Field(..., description="Unique ID for the virtual seal")
    # RT-2 R2 Fix 3 — PAN/CVV wrapped in SecretStr to prevent accidental leaks
    # through __str__, __repr__, f-string, json.dumps, pickle, slicing, .encode().
    # expiration_date stays as str (non-sensitive, must render in UX messages).
    card_number: Optional[SecretStr] = Field(default=None, description="Virtual credit card number")
    cvv: Optional[SecretStr] = Field(default=None, description="CVV security code")
    expiration_date: Optional[str] = Field(default=None, description="Expiration date in MM/YY format")
    authorized_amount: float = Field(..., ge=0, description="Amount authorized on the seal")
    status: str = Field(default="Issued", description="Status of the seal (e.g., Issued, Rejected, Revoked)")
    rejection_reason: Optional[str] = Field(default=None, description="Reason for rejection")

    def __repr__(self):
        return (f"VirtualSeal(seal_id={self.seal_id!r}, status={self.status!r}, "
                f"card_number='****-REDACTED', cvv='***', "
                f"authorized_amount={self.authorized_amount})")

    def __str__(self):
        return self.__repr__()
