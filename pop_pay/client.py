import uuid
from pop_pay.core.models import PaymentIntent, GuardrailPolicy, VirtualSeal
from pop_pay.providers.base import VirtualCardProvider
from pop_pay.engine.guardrails import GuardrailEngine
from pop_pay.core.state import PopStateTracker
from pop_pay.errors import PopPayLLMError

class PopClient:
    def __init__(self, provider: VirtualCardProvider, policy: GuardrailPolicy, engine: GuardrailEngine = None, db_path: str = None):
        self.provider = provider
        self.policy = policy
        from pop_pay.core.state import DEFAULT_DB_PATH
        self.state_tracker = PopStateTracker(db_path=db_path or DEFAULT_DB_PATH)
        self.engine = engine if engine is not None else GuardrailEngine()
        
    async def process_payment(self, intent: PaymentIntent) -> VirtualSeal:
        # Check daily budget
        if not self.state_tracker.can_spend(intent.requested_amount, self.policy.max_daily_budget):
            seal = VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason="Daily budget exceeded"
            )
            # Record rejection
            self.state_tracker.record_seal(
                seal.seal_id,
                seal.authorized_amount,
                intent.target_vendor,
                status=seal.status,
                rejection_reason=seal.rejection_reason,
            )
            return seal

        # Evaluate intent. Typed PopPayLLMError (RetryExhausted / ProviderUnreachable /
        # InvalidResponse) must be surfaced as evaluation-failure, not a guardrail block —
        # otherwise quota burn or transport faults masquerade as policy rejections.
        try:
            approved, reason = await self.engine.evaluate_intent(intent, self.policy)
        except PopPayLLMError as e:
            seal = VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason=f"evaluation_failed:{e.code}:{e}",
            )
            self.state_tracker.record_seal(
                seal.seal_id,
                seal.authorized_amount,
                intent.target_vendor,
                status=seal.status,
                rejection_reason=seal.rejection_reason,
            )
            return seal
        if not approved:
            seal = VirtualSeal(
                seal_id=str(uuid.uuid4()),
                authorized_amount=0.0,
                status="Rejected",
                rejection_reason=reason
            )
            # Record rejection
            self.state_tracker.record_seal(
                seal.seal_id,
                seal.authorized_amount,
                intent.target_vendor,
                status=seal.status,
                rejection_reason=seal.rejection_reason,
            )
            return seal
            
        # Issue card
        seal = await self.provider.issue_card(intent, self.policy)

        # Task B: Initial state should be 'Pending' if not rejected
        record_status = seal.status
        if record_status.lower() != "rejected":
            record_status = "Pending"
            seal.status = "Pending"

        # Record seal (success or rejection from provider) — only masked card stored
        self.state_tracker.record_seal(
            seal.seal_id,
            seal.authorized_amount,
            intent.target_vendor,
            status=record_status,
            masked_card=f"****-****-****-{seal.card_number.last4()}" if seal.card_number else "****-****-****-????",
            expiration_date=seal.expiration_date,
            rejection_reason=seal.rejection_reason,
        )
        
        if seal.status.lower() != "rejected":
            self.state_tracker.add_spend(intent.requested_amount)
        return seal

    async def execute_payment(self, seal_id: str, amount: float) -> dict:
        """Simulates an actual payment execution with burn-after-use enforcement."""
        if self.state_tracker.is_used(seal_id):
            return {"status": "rejected", "reason": "Burn-after-use enforced"}
        
        self.state_tracker.mark_used(seal_id)
        return {"status": "success", "amount": amount}
