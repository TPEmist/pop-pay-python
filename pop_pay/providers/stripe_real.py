import asyncio
import stripe
from pop_pay.providers.base import VirtualCardProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal
from pop_pay.core.secret_str import SecretStr
import uuid

class StripeIssuingProvider(VirtualCardProvider):
    def __init__(self, api_key: str):
        stripe.api_key = api_key
        self._cardholder_id: str | None = None

    async def issue_card(self, intent: PaymentIntent, policy: GuardrailPolicy) -> VirtualSeal:
        try:
            if intent.requested_amount > policy.max_amount_per_tx:
                return VirtualSeal(
                    seal_id=str(uuid.uuid4()),
                    authorized_amount=0.0,
                    status="Rejected",
                    rejection_reason="Amount exceeds policy limit"
                )

            # Create a Cardholder first as required (cached per instance)
            if self._cardholder_id is None:
                cardholder = await asyncio.to_thread(
                    stripe.issuing.Cardholder.create,
                    type='individual',
                    name='POP Agent',
                    billing={
                        'address': {
                            'line1': '123 AI St',
                            'city': 'San Francisco',
                            'state': 'CA',
                            'postal_code': '94105',
                            'country': 'US'
                        }
                    }
                )
                self._cardholder_id = cardholder.id

            # Create the virtual card using the cached cardholder id
            card = await asyncio.to_thread(
                stripe.issuing.Card.create,
                cardholder=self._cardholder_id,
                type='virtual',
                currency='usd',
                spending_controls={
                    'spending_limits': [
                        {
                            'amount': int(intent.requested_amount * 100),
                            'interval': 'all_time'
                        }
                    ]
                }
            )
            
            return VirtualSeal(
                seal_id=str(uuid.uuid4()),
                card_number=SecretStr(f"****{card.last4}"),
                cvv=SecretStr("***"),
                expiration_date=f"{card.exp_month}/{card.exp_year}",
                authorized_amount=intent.requested_amount,
                status="Issued"
            )
        except stripe.StripeError as e:
            return VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason=str(e)
            )
        except Exception as e:  # noqa: BLE001 — provider-boundary fallback; wrap any unknown error into a rejected VirtualSeal so the payment flow cannot crash
            return VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason=str(e)
            )
