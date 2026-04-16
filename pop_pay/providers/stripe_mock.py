import uuid
import random
from datetime import datetime, timedelta
from pop_pay.providers.base import VirtualCardProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal
from pop_pay.core.secret_str import SecretStr

class MockStripeProvider(VirtualCardProvider):
    async def issue_card(self, intent: PaymentIntent, policy: GuardrailPolicy) -> VirtualSeal:
        # Static defense check
        if intent.requested_amount > policy.max_amount_per_tx:
            return VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason=f"Exceeds single transaction limit of {policy.max_amount_per_tx}"
            )
        
        # Issue mock card
        card_number = SecretStr("".join([str(random.randint(0, 9)) for _ in range(16)]))
        cvv = SecretStr("".join([str(random.randint(0, 9)) for _ in range(3)]))
        
        # Expiry date is 1 year from now
        exp_date = datetime.now() + timedelta(days=365)
        expiration_date = exp_date.strftime("%m/%y")
        
        return VirtualSeal(
            seal_id=str(uuid.uuid4()),
            card_number=card_number,
            cvv=cvv,
            expiration_date=expiration_date,
            authorized_amount=intent.requested_amount,
            status="Issued"
        )
