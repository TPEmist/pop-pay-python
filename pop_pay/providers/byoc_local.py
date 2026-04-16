import os
import uuid
from dotenv import load_dotenv
from pop_pay.providers.base import VirtualCardProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal
from pop_pay.core.secret_str import SecretStr

class LocalVaultProvider(VirtualCardProvider):
    def __init__(self, creds: dict | None = None):
        load_dotenv()
        # S0.7 F1: prefer explicitly injected creds (vault path). Env fallback
        # is for users setting POP_BYOC_* manually in .env without a vault.
        # Plaintext PAN/CVV no longer round-trips through os.environ when
        # sourced from vault.
        creds = creds or {}
        self.card_number = SecretStr(creds.get("card_number") or os.getenv("POP_BYOC_NUMBER") or "")
        self.exp_month = creds.get("exp_month") or os.getenv("POP_BYOC_EXP_MONTH")
        self.exp_year = creds.get("exp_year") or os.getenv("POP_BYOC_EXP_YEAR")
        self.cvv = SecretStr(creds.get("cvv") or os.getenv("POP_BYOC_CVV") or "")

        # Billing fields are optional — empty string means "not configured"
        self._billing_first_name = os.getenv("POP_BILLING_FIRST_NAME", "").strip()
        self._billing_last_name  = os.getenv("POP_BILLING_LAST_NAME", "").strip()
        self._billing_street     = os.getenv("POP_BILLING_STREET", "").strip()
        self._billing_city       = os.getenv("POP_BILLING_CITY", "").strip()
        self._billing_state      = os.getenv("POP_BILLING_STATE", "").strip()
        self._billing_country    = os.getenv("POP_BILLING_COUNTRY", "").strip()
        self._billing_zip        = os.getenv("POP_BILLING_ZIP", "").strip()
        self._billing_email             = os.getenv("POP_BILLING_EMAIL", "").strip()
        self._billing_phone              = os.getenv("POP_BILLING_PHONE", "").strip()
        self._billing_phone_country_code = os.getenv("POP_BILLING_PHONE_COUNTRY_CODE", "").strip()

        if not all([self.card_number, self.exp_month, self.exp_year, self.cvv]):
            raise ValueError("Missing BYOC credentials. Configure via vault (`pop-pay init-vault`) or env (POP_BYOC_NUMBER, POP_BYOC_EXP_MONTH, POP_BYOC_EXP_YEAR, POP_BYOC_CVV).")

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
            "email":              self._billing_email,
            "phone":              self._billing_phone,
            "phone_country_code": self._billing_phone_country_code,
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
