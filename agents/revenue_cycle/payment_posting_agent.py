"""
Payment Posting Agent

Automates ERA (Electronic Remittance Advice) processing and payment posting
with reconciliation, variance detection, and adjustment management.
"""

from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

from platform_core.agents.base_agent import BaseAgent


# ============================================================================
# Input/Output Models
# ============================================================================


class PaymentMethod(str, Enum):
    """Payment method type"""
    EFT = "eft"  # Electronic funds transfer
    CHECK = "check"
    CREDIT_CARD = "credit_card"
    ACH = "ach"
    WIRE = "wire"


class AdjustmentReason(str, Enum):
    """Adjustment reason codes"""
    CONTRACTUAL = "contractual"  # Per contract with payer
    PATIENT_RESPONSIBILITY = "patient_responsibility"  # Deductible, copay, coinsurance
    WRITE_OFF = "write_off"  # Non-collectible
    ADMIN_ADJUSTMENT = "administrative_adjustment"
    TIMELY_FILING = "timely_filing"
    DUPLICATE = "duplicate"
    OTHER = "other"


class PaymentLineItem(BaseModel):
    """Individual line item payment"""
    claim_id: str
    service_date: str
    procedure_code: str
    billed_amount: float
    allowed_amount: float
    paid_amount: float
    patient_responsibility: float = Field(default=0.0)
    adjustments: list[dict[str, Any]] = Field(default_factory=list)


class ERAData(BaseModel):
    """Electronic Remittance Advice data"""
    era_id: str = Field(..., description="ERA transaction ID")
    payer_name: str
    payer_id: str
    check_number: Optional[str] = None
    payment_date: str
    payment_method: PaymentMethod
    total_payment_amount: float

    line_items: list[PaymentLineItem]

    # Raw EDI data (optional)
    raw_edi_835: Optional[str] = None


class PaymentPostingInput(BaseModel):
    """Input for payment posting"""
    era_data: ERAData

    # Optional: Match with existing claims
    auto_match_claims: bool = Field(default=True, description="Automatically match payments to claims")
    post_to_patient_accounts: bool = Field(default=True, description="Post patient responsibility to patient accounts")

    # Variance thresholds
    variance_threshold_dollars: float = Field(default=5.0, description="Flag if variance > this amount")
    variance_threshold_percent: float = Field(default=0.10, description="Flag if variance > this percent")

    action: Literal["process", "reconcile", "report"] = "process"


class ClaimPayment(BaseModel):
    """Payment matched to specific claim"""
    claim_id: str
    service_date: str
    billed_amount: float
    allowed_amount: float
    paid_amount: float
    patient_responsibility: float
    adjustments: list[dict[str, Any]]

    # Reconciliation
    expected_amount: Optional[float] = None
    variance_amount: float = Field(default=0.0)
    variance_percent: float = Field(default=0.0)
    variance_reason: Optional[str] = None


class VarianceAlert(BaseModel):
    """Payment variance requiring review"""
    claim_id: str
    severity: str = Field(..., description="low, medium, high")
    variance_type: str = Field(..., description="underpayment, overpayment, unexpected_adjustment")
    amount_difference: float
    percent_difference: float
    description: str
    recommended_action: str


class PatientBalance(BaseModel):
    """Patient account balance update"""
    patient_id: str
    claim_id: str
    previous_balance: float
    new_charges: float
    payment_received: float
    adjustments: float
    new_balance: float


class ReconciliationSummary(BaseModel):
    """Summary of payment reconciliation"""
    total_claims_processed: int
    total_amount_posted: float
    total_adjustments: float
    total_patient_responsibility: float

    matched_payments: int
    unmatched_payments: int
    variance_alerts: int

    contractual_adjustments: float
    patient_responsibility_adjustments: float
    write_offs: float


class PaymentPostingOutput(BaseModel):
    """Output from payment posting"""
    success: bool
    era_id: str
    posting_date: str

    # Processed payments
    claim_payments: list[ClaimPayment]

    # Patient account updates
    patient_balances: list[PatientBalance] = Field(default_factory=list)

    # Reconciliation
    reconciliation_summary: ReconciliationSummary
    variance_alerts: list[VarianceAlert] = Field(default_factory=list)

    # Unmatched items
    unmatched_line_items: list[PaymentLineItem] = Field(default_factory=list)

    # Next steps
    next_steps: list[str]
    requires_manual_review: bool

    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool


# ============================================================================
# Agent Implementation
# ============================================================================


class PaymentPostingAgent(BaseAgent[PaymentPostingInput, PaymentPostingOutput]):
    """
    Automates ERA processing and payment posting with reconciliation.

    Features:
    - Automatic payment-to-claim matching
    - Variance detection and alerting
    - Adjustment categorization and posting
    - Patient balance updates
    - Reconciliation reporting
    - Integration with claims management system

    Integration:
    - Claims Generation Agent (match payments to claims)
    - Claims Status Tracking Agent (update claim status)
    - Patient billing system (update patient balances)
    """

    def __init__(self):
        super().__init__()

    async def _execute_internal(
        self,
        input_data: PaymentPostingInput,
        context: dict[str, Any]
    ) -> PaymentPostingOutput:
        """Execute payment posting workflow"""

        if input_data.action == "process":
            return await self._process_payment(input_data, context)
        elif input_data.action == "reconcile":
            return await self._reconcile_payment(input_data, context)
        elif input_data.action == "report":
            return await self._generate_report(input_data, context)
        else:
            raise ValueError(f"Unknown action: {input_data.action}")

    async def _process_payment(
        self,
        input_data: PaymentPostingInput,
        context: dict[str, Any]
    ) -> PaymentPostingOutput:
        """Process ERA and post payments"""

        era = input_data.era_data

        # Step 1: Match payments to claims
        claim_payments = await self._match_payments_to_claims(
            era.line_items,
            input_data.auto_match_claims
        )

        # Step 2: Detect and categorize variances
        variance_alerts = self._detect_variances(
            claim_payments,
            input_data.variance_threshold_dollars,
            input_data.variance_threshold_percent
        )

        # Step 3: Update patient balances
        patient_balances = []
        if input_data.post_to_patient_accounts:
            patient_balances = self._calculate_patient_balances(claim_payments)

        # Step 4: Identify unmatched payments
        matched_claim_ids = {cp.claim_id for cp in claim_payments}
        unmatched = [
            item for item in era.line_items
            if item.claim_id not in matched_claim_ids
        ]

        # Step 5: Generate reconciliation summary
        reconciliation = self._generate_reconciliation_summary(
            claim_payments,
            variance_alerts,
            unmatched
        )

        # Step 6: Determine next steps
        next_steps = self._determine_next_steps(
            claim_payments,
            variance_alerts,
            unmatched
        )

        # Step 7: Calculate confidence
        confidence = self._calculate_confidence(
            claim_payments,
            variance_alerts,
            unmatched
        )

        requires_manual_review = (
            len(variance_alerts) > 0 or
            len(unmatched) > 0 or
            confidence < 0.90
        )

        return PaymentPostingOutput(
            success=True,
            era_id=era.era_id,
            posting_date=datetime.now().strftime("%Y-%m-%d"),
            claim_payments=claim_payments,
            patient_balances=patient_balances,
            reconciliation_summary=reconciliation,
            variance_alerts=variance_alerts,
            unmatched_line_items=unmatched,
            next_steps=next_steps,
            requires_manual_review=requires_manual_review,
            confidence=confidence,
            needs_human_review=requires_manual_review
        )

    async def _match_payments_to_claims(
        self,
        line_items: list[PaymentLineItem],
        auto_match: bool
    ) -> list[ClaimPayment]:
        """Match ERA line items to claims"""

        # In production, this would:
        # 1. Query claims database by claim_id
        # 2. Retrieve expected payment amounts
        # 3. Match by multiple criteria (claim ID, service date, patient, amount)
        # 4. Handle partial payments and splits

        claim_payments = []

        for item in line_items:
            # Mock: Retrieve expected amount for claim
            expected_amount = self._get_expected_payment_amount(item.claim_id)

            # Calculate variance
            variance_amount = item.paid_amount - expected_amount if expected_amount else 0.0
            variance_percent = (
                (variance_amount / expected_amount * 100) if expected_amount and expected_amount > 0 else 0.0
            )

            # Determine variance reason
            variance_reason = None
            if abs(variance_amount) > 1.0:  # More than $1 difference
                if variance_amount < 0:
                    variance_reason = "Underpayment detected"
                else:
                    variance_reason = "Overpayment detected"

            claim_payment = ClaimPayment(
                claim_id=item.claim_id,
                service_date=item.service_date,
                billed_amount=item.billed_amount,
                allowed_amount=item.allowed_amount,
                paid_amount=item.paid_amount,
                patient_responsibility=item.patient_responsibility,
                adjustments=item.adjustments,
                expected_amount=expected_amount,
                variance_amount=variance_amount,
                variance_percent=variance_percent,
                variance_reason=variance_reason
            )

            claim_payments.append(claim_payment)

        return claim_payments

    def _get_expected_payment_amount(self, claim_id: str) -> float:
        """Get expected payment for claim (mock)"""
        # In production, query from claims database
        # For now, return mock expected amount
        return 225.00

    def _detect_variances(
        self,
        claim_payments: list[ClaimPayment],
        threshold_dollars: float,
        threshold_percent: float
    ) -> list[VarianceAlert]:
        """Detect payment variances requiring review"""

        alerts = []

        for payment in claim_payments:
            if not payment.expected_amount:
                continue

            # Check if variance exceeds thresholds
            variance_amount = abs(payment.variance_amount)
            variance_percent = abs(payment.variance_percent)

            if variance_amount < threshold_dollars and variance_percent < (threshold_percent * 100):
                continue  # Within acceptable range

            # Determine severity
            severity = "low"
            if variance_amount > threshold_dollars * 3 or variance_percent > (threshold_percent * 100 * 3):
                severity = "high"
            elif variance_amount > threshold_dollars * 1.5 or variance_percent > (threshold_percent * 100 * 1.5):
                severity = "medium"

            # Determine variance type
            variance_type = "underpayment" if payment.variance_amount < 0 else "overpayment"

            # Check for unexpected adjustments
            contractual_adjustment = sum(
                adj.get("amount", 0) for adj in payment.adjustments
                if adj.get("reason") == AdjustmentReason.CONTRACTUAL
            )
            if abs(contractual_adjustment) > threshold_dollars * 2:
                variance_type = "unexpected_adjustment"

            # Recommended action
            if variance_type == "underpayment" and severity in ["high", "medium"]:
                action = "Review contract rates and consider appeal"
            elif variance_type == "overpayment":
                action = "Verify payment accuracy and prepare for potential recoupment"
            elif variance_type == "unexpected_adjustment":
                action = "Review adjustment reason codes and contract terms"
            else:
                action = "Review payment and verify accuracy"

            alert = VarianceAlert(
                claim_id=payment.claim_id,
                severity=severity,
                variance_type=variance_type,
                amount_difference=payment.variance_amount,
                percent_difference=payment.variance_percent,
                description=f"Payment variance of ${payment.variance_amount:.2f} ({payment.variance_percent:.1f}%)",
                recommended_action=action
            )

            alerts.append(alert)

        return alerts

    def _calculate_patient_balances(
        self,
        claim_payments: list[ClaimPayment]
    ) -> list[PatientBalance]:
        """Calculate updated patient account balances"""

        # In production, this would:
        # 1. Query patient account balances by patient_id
        # 2. Calculate new balances
        # 3. Post to patient billing system

        # Group by patient (mock - would need patient_id from claim)
        patient_balances = []

        for payment in claim_payments:
            # Mock patient_id extraction (would come from claim record)
            patient_id = f"PAT_{payment.claim_id.split('-')[0]}"

            # Mock previous balance
            previous_balance = 150.00

            # New charges from this claim
            new_charges = payment.patient_responsibility

            # Calculate adjustments (write-offs, etc.)
            adjustments = sum(
                adj.get("amount", 0) for adj in payment.adjustments
                if adj.get("reason") == AdjustmentReason.WRITE_OFF
            )

            # New balance
            new_balance = previous_balance + new_charges + adjustments

            patient_balance = PatientBalance(
                patient_id=patient_id,
                claim_id=payment.claim_id,
                previous_balance=previous_balance,
                new_charges=new_charges,
                payment_received=0.0,  # This tracks patient payments, not insurance
                adjustments=adjustments,
                new_balance=new_balance
            )

            patient_balances.append(patient_balance)

        return patient_balances

    def _generate_reconciliation_summary(
        self,
        claim_payments: list[ClaimPayment],
        variance_alerts: list[VarianceAlert],
        unmatched: list[PaymentLineItem]
    ) -> ReconciliationSummary:
        """Generate reconciliation summary"""

        total_posted = sum(p.paid_amount for p in claim_payments)
        total_adjustments = sum(
            sum(adj.get("amount", 0) for adj in p.adjustments)
            for p in claim_payments
        )
        total_patient_resp = sum(p.patient_responsibility for p in claim_payments)

        # Categorize adjustments
        contractual = sum(
            sum(
                adj.get("amount", 0) for adj in p.adjustments
                if adj.get("reason") == AdjustmentReason.CONTRACTUAL
            )
            for p in claim_payments
        )

        patient_resp_adj = sum(
            sum(
                adj.get("amount", 0) for adj in p.adjustments
                if adj.get("reason") == AdjustmentReason.PATIENT_RESPONSIBILITY
            )
            for p in claim_payments
        )

        write_offs = sum(
            sum(
                adj.get("amount", 0) for adj in p.adjustments
                if adj.get("reason") == AdjustmentReason.WRITE_OFF
            )
            for p in claim_payments
        )

        return ReconciliationSummary(
            total_claims_processed=len(claim_payments),
            total_amount_posted=total_posted,
            total_adjustments=total_adjustments,
            total_patient_responsibility=total_patient_resp,
            matched_payments=len(claim_payments),
            unmatched_payments=len(unmatched),
            variance_alerts=len(variance_alerts),
            contractual_adjustments=contractual,
            patient_responsibility_adjustments=patient_resp_adj,
            write_offs=write_offs
        )

    def _determine_next_steps(
        self,
        claim_payments: list[ClaimPayment],
        variance_alerts: list[VarianceAlert],
        unmatched: list[PaymentLineItem]
    ) -> list[str]:
        """Determine next steps for payment processing"""

        steps = []

        if len(claim_payments) > 0:
            steps.append(f"Post {len(claim_payments)} payments to claim accounts")

        if len(variance_alerts) > 0:
            high_severity = sum(1 for a in variance_alerts if a.severity == "high")
            if high_severity > 0:
                steps.append(f"⚠️ Review {high_severity} high-severity payment variances immediately")
            steps.append(f"Review {len(variance_alerts)} variance alert(s)")

        if len(unmatched) > 0:
            steps.append(f"⚠️ Investigate {len(unmatched)} unmatched payment(s)")

        patient_resp = sum(p.patient_responsibility for p in claim_payments)
        if patient_resp > 0:
            steps.append(f"Generate patient statements for ${patient_resp:.2f} in patient responsibility")

        steps.append("Update claim status in management system")
        steps.append("Archive ERA in document management system")

        return steps

    def _calculate_confidence(
        self,
        claim_payments: list[ClaimPayment],
        variance_alerts: list[VarianceAlert],
        unmatched: list[PaymentLineItem]
    ) -> float:
        """Calculate confidence in payment posting"""

        confidence = 1.0

        # Reduce for unmatched payments
        if len(unmatched) > 0:
            match_rate = len(claim_payments) / (len(claim_payments) + len(unmatched))
            confidence *= match_rate

        # Reduce for variances
        if len(variance_alerts) > 0:
            high_severity = sum(1 for a in variance_alerts if a.severity == "high")
            medium_severity = sum(1 for a in variance_alerts if a.severity == "medium")

            confidence -= (high_severity * 0.15)
            confidence -= (medium_severity * 0.08)

        # Reduce if many adjustments
        total_claims = len(claim_payments)
        claims_with_adjustments = sum(1 for p in claim_payments if len(p.adjustments) > 2)
        if total_claims > 0 and claims_with_adjustments / total_claims > 0.5:
            confidence -= 0.10

        return max(confidence, 0.0)

    async def _reconcile_payment(
        self,
        input_data: PaymentPostingInput,
        context: dict[str, Any]
    ) -> PaymentPostingOutput:
        """Reconcile ERA with expected payments"""

        # This would perform detailed reconciliation:
        # 1. Compare ERA totals with expected totals
        # 2. Verify all claims are accounted for
        # 3. Check for duplicate payments
        # 4. Validate adjustment reason codes

        # For now, delegate to process_payment
        return await self._process_payment(input_data, context)

    async def _generate_report(
        self,
        input_data: PaymentPostingInput,
        context: dict[str, Any]
    ) -> PaymentPostingOutput:
        """Generate payment posting report"""

        # Process the payment first
        result = await self._process_payment(input_data, context)

        # In production, this would generate formatted reports:
        # 1. Payment posting summary report
        # 2. Variance analysis report
        # 3. Aging report updates
        # 4. Financial reconciliation report

        result.next_steps.append("Generate payment posting summary report")
        result.next_steps.append("Distribute variance analysis to billing team")

        return result
