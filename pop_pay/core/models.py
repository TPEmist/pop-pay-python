from pydantic import BaseModel, Field
from typing import List, Optional

class GuardrailPolicy(BaseModel):
    allowed_categories: List[str] = Field(default_factory=list, description="Categories allowed for payment")
    max_amount_per_tx: float = Field(..., gt=0, description="Max amount per transaction")
    max_daily_budget: float = Field(..., gt=0, description="Max daily budget")
    block_hallucination_loops: bool = Field(default=True, description="Whether to block potential hallucination loops")

class PaymentIntent(BaseModel):
    agent_id: str = Field(..., description="ID of the AI agent requesting payment")
    requested_amount: float = Field(..., gt=0, description="Amount requested")
    target_vendor: str = Field(..., max_length=200, description="Vendor to pay")
    reasoning: str = Field(..., max_length=2000, description="Agent reasoning for the payment")
    page_url: Optional[str] = Field(default=None, description="Current checkout page URL for domain validation")

class VirtualSeal(BaseModel):
    seal_id: str = Field(..., description="Unique ID for the virtual seal")
    card_number: Optional[str] = Field(default=None, description="Virtual credit card number")
    cvv: Optional[str] = Field(default=None, description="CVV security code")
    expiration_date: Optional[str] = Field(default=None, description="Expiration date in MM/YY format")
    authorized_amount: float = Field(..., ge=0, description="Amount authorized on the seal")
    status: str = Field(default="Issued", description="Status of the seal (e.g., Issued, Rejected, Revoked)")
    rejection_reason: Optional[str] = Field(default=None, description="Reason for rejection")
