import os
import uuid
from dotenv import load_dotenv
from pop_pay.providers.base import VirtualCardProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal

class LocalVaultProvider(VirtualCardProvider):
    def __init__(self):
        load_dotenv()
        self.card_number = os.getenv("POP_BYOC_NUMBER")
        self.exp_month = os.getenv("POP_BYOC_EXP_MONTH")
        self.exp_year = os.getenv("POP_BYOC_EXP_YEAR")
        self.cvv = os.getenv("POP_BYOC_CVV")

        # Billing fields are optional — empty string means "not configured"
        self._billing_first_name = os.getenv("POP_BILLING_FIRST_NAME", "").strip()
        self._billing_last_name  = os.getenv("POP_BILLING_LAST_NAME", "").strip()
        self._billing_street     = os.getenv("POP_BILLING_STREET", "").strip()
        self._billing_city       = os.getenv("POP_BILLING_CITY", "").strip()
        self._billing_state      = os.getenv("POP_BILLING_STATE", "").strip()
        self._billing_country    = os.getenv("POP_BILLING_COUNTRY", "").strip()
        self._billing_zip        = os.getenv("POP_BILLING_ZIP", "").strip()
        self._billing_email = os.getenv("POP_BILLING_EMAIL", "").strip()
        self._billing_phone = os.getenv("POP_BILLING_PHONE", "").strip()  # E.164, e.g. +14155551234

        if not all([self.card_number, self.exp_month, self.exp_year, self.cvv]):
            raise ValueError("Missing BYOC environment variables. Please check POP_BYOC_NUMBER, POP_BYOC_EXP_MONTH, POP_BYOC_EXP_YEAR, POP_BYOC_CVV in .env.")

    @property
    def billing_info(self) -> dict:
        """Return billing details as a dict; empty-string values mean not configured."""
        return {
            "first_name": self._billing_first_name,
            "last_name":  self._billing_last_name,
            "street":     self._billing_street,
            "city":       self._billing_city,
            "state":      self._billing_state,
            "country":    self._billing_country,
            "zip":        self._billing_zip,
            "email": self._billing_email,
            "phone": self._billing_phone,
        }

    async def issue_card(self, intent: PaymentIntent, policy: GuardrailPolicy) -> VirtualSeal:
        if intent.requested_amount > policy.max_amount_per_tx:
            return VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason="Amount exceeds policy limit"
            )

        return VirtualSeal(
            seal_id=str(uuid.uuid4()),
            card_number=self.card_number,
            cvv=self.cvv,
            expiration_date=f"{self.exp_month}/{self.exp_year}",
            authorized_amount=intent.requested_amount,
            status="Issued"
        )
