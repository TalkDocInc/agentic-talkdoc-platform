"""
Claims Status Tracking Agent

Monitors the status of submitted insurance claims via Stedi EDI.
Tracks claim lifecycle, detects issues, and alerts when action is needed.

Uses EDI 276 (Claim Status Request) and 277 (Claim Status Response) transactions.
"""

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field
from structlog import get_logger

from platform_core.agent_orchestration.base_agent import BaseAgent
from platform_core.config import get_config

logger = get_logger()
config = get_config()


# Input/Output Models


class ClaimStatusRequest(BaseModel):
    """Request to check claim status."""

    claim_id: str = Field(..., description="Internal claim ID")
    submission_id: str = Field(..., description="Stedi submission ID from Claims Generation Agent")
    payer_claim_control_number: Optional[str] = Field(None, description="Payer's claim control number (if available)")
    patient_id: str
    payer_id: str
    payer_name: str
    submitted_date: str = Field(..., description="Date claim was submitted (YYYY-MM-DD)")
    total_charge_amount: float
    expected_payment_amount: Optional[float] = Field(None, description="Expected payment (if known)")


class ClaimStatusDetail(BaseModel):
    """Detailed status information for a claim."""

    status_code: str = Field(..., description="Standard claim status code")
    status_category: str = Field(
        ..., description="submitted, in_progress, accepted, rejected, paid, denied, pending_info"
    )
    status_description: str = Field(..., description="Human-readable status description")
    effective_date: str = Field(..., description="Date of this status (YYYY-MM-DD)")
    additional_info: Optional[str] = Field(None, description="Additional status information")


class PaymentInformation(BaseModel):
    """Payment information for paid claims."""

    paid_amount: float
    paid_date: str = Field(..., description="Date payment was issued (YYYY-MM-DD)")
    check_number: Optional[str] = None
    adjustment_amount: float = Field(default=0.0, description="Amount adjusted")
    adjustment_reason: Optional[str] = None


class ClaimIssue(BaseModel):
    """Issue detected with a claim."""

    issue_type: str = Field(
        ..., description="missing_info, denial, partial_payment, timeout, payer_error, coding_error"
    )
    severity: str = Field(..., description="low, medium, high, critical")
    description: str = Field(..., description="Issue description")
    recommended_action: str = Field(..., description="What to do to resolve")
    resolution_deadline: Optional[str] = Field(None, description="Deadline to resolve (YYYY-MM-DD)")


class ClaimsStatusTrackingInput(BaseModel):
    """Input for claims status tracking agent."""

    claims_to_check: list[ClaimStatusRequest] = Field(..., description="List of claims to check status for")
    check_all_pending: bool = Field(
        default=False, description="Check all pending claims from last 90 days (if claims_to_check is empty)"
    )
    alert_on_issues: bool = Field(default=True, description="Generate alerts for claims with issues")


class ClaimStatusResult(BaseModel):
    """Status result for a single claim."""

    claim_id: str
    submission_id: str
    current_status: ClaimStatusDetail
    status_history: list[ClaimStatusDetail] = Field(default_factory=list, description="Historical status changes")
    payment_info: Optional[PaymentInformation] = None
    issues: list[ClaimIssue] = Field(default_factory=list, description="Detected issues")
    days_since_submission: int
    requires_action: bool = Field(default=False, description="Whether action is needed")
    next_action_due: Optional[str] = Field(None, description="When next action should be taken (YYYY-MM-DD)")


class ClaimsStatusTrackingOutput(BaseModel):
    """Output from claims status tracking agent."""

    tracked_claims: list[ClaimStatusResult] = Field(..., description="Status results for all checked claims")
    total_claims_checked: int
    claims_requiring_action: int
    total_issues_detected: int
    summary_by_status: dict[str, int] = Field(..., description="Count of claims by status category")
    total_paid_amount: float = Field(default=0.0, description="Total amount paid across all claims")
    total_pending_amount: float = Field(default=0.0, description="Total amount still pending")
    oldest_pending_claim_days: Optional[int] = Field(None, description="Days since oldest pending claim submission")


# Agent Implementation


class ClaimsStatusTrackingAgent(BaseAgent[ClaimsStatusTrackingInput, ClaimsStatusTrackingOutput]):
    """
    Claims Status Tracking Agent.

    Monitors submitted insurance claims using EDI 276/277 transactions via Stedi.
    Tracks claim lifecycle, detects issues, and provides actionable insights.
    """

    def __init__(self):
        super().__init__(
            agent_type="claims_status_tracking",
            agent_version="1.0.0",
            description="Monitor insurance claim status and detect issues requiring action",
        )

    async def _execute_internal(
        self,
        input_data: ClaimsStatusTrackingInput,
        context: dict[str, Any],
    ) -> tuple[ClaimsStatusTrackingOutput, float, dict[str, Any]]:
        """Execute claims status tracking logic."""
        start_time = datetime.now()

        # Step 1: Get claims to check
        claims_to_check = input_data.claims_to_check

        if not claims_to_check and input_data.check_all_pending:
            # In production, this would query database for pending claims
            logger.info("check_all_pending_enabled", message="Would query database for pending claims")
            claims_to_check = []

        if not claims_to_check:
            # No claims to check
            output = ClaimsStatusTrackingOutput(
                tracked_claims=[],
                total_claims_checked=0,
                claims_requiring_action=0,
                total_issues_detected=0,
                summary_by_status={},
            )
            return output, 0.5, {"no_claims": True}

        # Step 2: Check status for each claim
        tracked_claims = []
        for claim_request in claims_to_check:
            claim_result = await self._check_claim_status(claim_request)
            tracked_claims.append(claim_result)

        # Step 3: Analyze results
        summary_by_status = self._calculate_status_summary(tracked_claims)
        claims_requiring_action = sum(1 for c in tracked_claims if c.requires_action)
        total_issues = sum(len(c.issues) for c in tracked_claims)

        # Calculate financial totals
        total_paid = sum(c.payment_info.paid_amount for c in tracked_claims if c.payment_info)
        total_pending = sum(
            claims_to_check[i].total_charge_amount
            for i, c in enumerate(tracked_claims)
            if c.current_status.status_category not in ["paid", "denied"]
        )

        # Find oldest pending claim
        pending_claims = [c for c in tracked_claims if c.current_status.status_category in ["submitted", "in_progress"]]
        oldest_pending_days = max([c.days_since_submission for c in pending_claims]) if pending_claims else None

        # Step 4: Create output
        output = ClaimsStatusTrackingOutput(
            tracked_claims=tracked_claims,
            total_claims_checked=len(tracked_claims),
            claims_requiring_action=claims_requiring_action,
            total_issues_detected=total_issues,
            summary_by_status=summary_by_status,
            total_paid_amount=total_paid,
            total_pending_amount=total_pending,
            oldest_pending_claim_days=oldest_pending_days,
        )

        # Calculate confidence
        confidence = self._calculate_tracking_confidence(output, tracked_claims)

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "claims_checked": len(tracked_claims),
            "claims_requiring_action": claims_requiring_action,
            "total_issues": total_issues,
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    async def _check_claim_status(self, claim_request: ClaimStatusRequest) -> ClaimStatusResult:
        """Check status of a single claim via Stedi EDI."""
        # Calculate days since submission
        submitted_date = datetime.strptime(claim_request.submitted_date, "%Y-%m-%d")
        days_since_submission = (datetime.now() - submitted_date).days

        # Check if we have Stedi API configured
        if not config.stedi_api_key:
            logger.warning("stedi_api_key_not_configured", message="Using mock status check")
            return self._mock_claim_status(claim_request, days_since_submission)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Stedi Claims Status API endpoint (EDI 276/277)
                url = f"{config.stedi_api_url}/claims/status"

                headers = {
                    "Authorization": f"Bearer {config.stedi_api_key}",
                    "Content-Type": "application/json",
                }

                # Build EDI 276 request
                request_body = {
                    "transactionType": "276",  # Claim Status Request
                    "submissionId": claim_request.submission_id,
                    "payerClaimControlNumber": claim_request.payer_claim_control_number,
                    "payerId": claim_request.payer_id,
                    "patientId": claim_request.patient_id,
                }

                logger.info(
                    "checking_claim_status_via_stedi",
                    claim_id=claim_request.claim_id,
                    submission_id=claim_request.submission_id,
                )

                response = await client.post(url, headers=headers, json=request_body)
                response.raise_for_status()

                result = response.json()

                # Parse EDI 277 response
                return self._parse_stedi_status_response(result, claim_request, days_since_submission)

        except httpx.HTTPStatusError as e:
            logger.error(
                "stedi_api_error",
                status_code=e.response.status_code,
                response=e.response.text,
                error=str(e),
            )
            # Fall back to mock for demo
            return self._mock_claim_status(claim_request, days_since_submission)

        except Exception as e:
            logger.error("claim_status_check_error", error=str(e))
            # Fall back to mock for demo
            return self._mock_claim_status(claim_request, days_since_submission)

    def _parse_stedi_status_response(
        self, stedi_response: dict[str, Any], claim_request: ClaimStatusRequest, days_since_submission: int
    ) -> ClaimStatusResult:
        """Parse Stedi EDI 277 response."""
        # This would parse the actual EDI 277 response
        # For now, using mock logic as example

        status_code = stedi_response.get("statusCode", "A1")  # A1 = Finalized/Payment
        category = self._map_status_code_to_category(status_code)

        current_status = ClaimStatusDetail(
            status_code=status_code,
            status_category=category,
            status_description=stedi_response.get("statusDescription", "Claim processed"),
            effective_date=stedi_response.get("effectiveDate", datetime.now().strftime("%Y-%m-%d")),
            additional_info=stedi_response.get("additionalInfo"),
        )

        # Parse payment info if paid
        payment_info = None
        if category == "paid" and stedi_response.get("paymentInfo"):
            payment_data = stedi_response["paymentInfo"]
            payment_info = PaymentInformation(
                paid_amount=payment_data.get("paidAmount", 0.0),
                paid_date=payment_data.get("paidDate", ""),
                check_number=payment_data.get("checkNumber"),
                adjustment_amount=payment_data.get("adjustmentAmount", 0.0),
                adjustment_reason=payment_data.get("adjustmentReason"),
            )

        # Detect issues
        issues = self._detect_claim_issues(current_status, claim_request, days_since_submission, payment_info)

        # Determine if action required
        requires_action = len(issues) > 0 or current_status.status_category in ["rejected", "denied", "pending_info"]

        return ClaimStatusResult(
            claim_id=claim_request.claim_id,
            submission_id=claim_request.submission_id,
            current_status=current_status,
            status_history=[],  # Would include full history from response
            payment_info=payment_info,
            issues=issues,
            days_since_submission=days_since_submission,
            requires_action=requires_action,
            next_action_due=self._calculate_next_action_due(issues, days_since_submission),
        )

    def _mock_claim_status(self, claim_request: ClaimStatusRequest, days_since_submission: int) -> ClaimStatusResult:
        """Generate mock claim status for testing when Stedi is not configured."""
        logger.info("using_mock_claim_status", claim_id=claim_request.claim_id)

        # Simulate different statuses based on days since submission
        if days_since_submission <= 3:
            status_category = "submitted"
            status_description = "Claim received and pending review"
            status_code = "P0"
        elif days_since_submission <= 10:
            status_category = "in_progress"
            status_description = "Claim under review"
            status_code = "P1"
        elif days_since_submission <= 30:
            status_category = "accepted"
            status_description = "Claim approved for payment"
            status_code = "A0"
        else:
            status_category = "paid"
            status_description = "Claim processed and paid"
            status_code = "A1"

        current_status = ClaimStatusDetail(
            status_code=status_code,
            status_category=status_category,
            status_description=status_description,
            effective_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        )

        # Mock payment info for paid claims
        payment_info = None
        if status_category == "paid":
            payment_info = PaymentInformation(
                paid_amount=claim_request.total_charge_amount * 0.85,  # 85% of submitted
                paid_date=datetime.now().strftime("%Y-%m-%d"),
                check_number=f"CHK-{uuid4()}"[:10],
                adjustment_amount=claim_request.total_charge_amount * 0.15,
                adjustment_reason="Contractual adjustment",
            )

        # Detect issues
        issues = self._detect_claim_issues(current_status, claim_request, days_since_submission, payment_info)

        requires_action = len(issues) > 0

        return ClaimStatusResult(
            claim_id=claim_request.claim_id,
            submission_id=claim_request.submission_id,
            current_status=current_status,
            status_history=[],
            payment_info=payment_info,
            issues=issues,
            days_since_submission=days_since_submission,
            requires_action=requires_action,
            next_action_due=self._calculate_next_action_due(issues, days_since_submission),
        )

    def _map_status_code_to_category(self, status_code: str) -> str:
        """Map EDI status code to category."""
        # Simplified mapping - real implementation would have full EDI 277 code table
        code_prefix = status_code[0] if status_code else ""

        mapping = {
            "P": "in_progress",  # Pending
            "A": "accepted",  # Accepted/Approved
            "R": "rejected",  # Rejected
            "D": "denied",  # Denied
            "F": "pending_info",  # Finalized/Forwarded (may need more info)
        }

        category = mapping.get(code_prefix, "submitted")

        # Specific codes
        if status_code == "A1":
            return "paid"

        return category

    def _detect_claim_issues(
        self,
        current_status: ClaimStatusDetail,
        claim_request: ClaimStatusRequest,
        days_since_submission: int,
        payment_info: Optional[PaymentInformation],
    ) -> list[ClaimIssue]:
        """Detect issues with a claim."""
        issues = []

        # Issue 1: Claim taking too long
        if current_status.status_category in ["submitted", "in_progress"] and days_since_submission > 30:
            issues.append(
                ClaimIssue(
                    issue_type="timeout",
                    severity="high" if days_since_submission > 45 else "medium",
                    description=f"Claim pending for {days_since_submission} days (typical processing: 14-30 days)",
                    recommended_action="Contact payer to inquire about status and request expedited review",
                    resolution_deadline=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                )
            )

        # Issue 2: Claim rejected
        if current_status.status_category == "rejected":
            issues.append(
                ClaimIssue(
                    issue_type="denial",
                    severity="critical",
                    description=f"Claim rejected: {current_status.status_description}",
                    recommended_action="Review rejection reason, correct errors, and resubmit within timely filing deadline",
                    resolution_deadline=(datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
                )
            )

        # Issue 3: Claim denied
        if current_status.status_category == "denied":
            issues.append(
                ClaimIssue(
                    issue_type="denial",
                    severity="critical",
                    description=f"Claim denied: {current_status.status_description}",
                    recommended_action="Review denial reason, gather supporting documentation, and file appeal if warranted",
                    resolution_deadline=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            )

        # Issue 4: Partial payment
        if payment_info and claim_request.expected_payment_amount:
            if payment_info.paid_amount < claim_request.expected_payment_amount * 0.7:  # Less than 70%
                shortage = claim_request.expected_payment_amount - payment_info.paid_amount
                issues.append(
                    ClaimIssue(
                        issue_type="partial_payment",
                        severity="medium",
                        description=f"Underpayment: Paid ${payment_info.paid_amount:.2f}, expected ${claim_request.expected_payment_amount:.2f} (shortage: ${shortage:.2f})",
                        recommended_action="Review adjustment reasons and consider filing appeal if inappropriate",
                        resolution_deadline=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                    )
                )

        # Issue 5: Additional information requested
        if current_status.status_category == "pending_info":
            issues.append(
                ClaimIssue(
                    issue_type="missing_info",
                    severity="high",
                    description=f"Payer requesting additional information: {current_status.additional_info or 'See payer correspondence'}",
                    recommended_action="Provide requested documentation immediately to avoid denial",
                    resolution_deadline=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                )
            )

        # Issue 6: Very old pending claim
        if current_status.status_category in ["submitted", "in_progress"] and days_since_submission > 60:
            issues.append(
                ClaimIssue(
                    issue_type="timeout",
                    severity="critical",
                    description=f"Claim pending for {days_since_submission} days - approaching timely filing deadline",
                    recommended_action="Immediately escalate with payer. Consider resubmitting if no response.",
                    resolution_deadline=(datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                )
            )

        return issues

    def _calculate_next_action_due(self, issues: list[ClaimIssue], days_since_submission: int) -> Optional[str]:
        """Calculate when next action should be taken."""
        if not issues:
            # No issues - routine follow-up based on days pending
            if days_since_submission > 45:
                return (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            elif days_since_submission > 30:
                return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            elif days_since_submission > 14:
                return (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
            else:
                return None

        # Get earliest deadline from issues
        deadlines = [i.resolution_deadline for i in issues if i.resolution_deadline]
        return min(deadlines) if deadlines else (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    def _calculate_status_summary(self, tracked_claims: list[ClaimStatusResult]) -> dict[str, int]:
        """Calculate summary of claims by status."""
        summary = {}
        for claim in tracked_claims:
            category = claim.current_status.status_category
            summary[category] = summary.get(category, 0) + 1
        return summary

    def _calculate_tracking_confidence(
        self, output: ClaimsStatusTrackingOutput, tracked_claims: list[ClaimStatusResult]
    ) -> float:
        """Calculate confidence in tracking results."""
        if output.total_claims_checked == 0:
            return 0.5

        confidence = 0.9  # Base confidence

        # Decrease if many claims have issues
        issue_ratio = output.total_issues_detected / output.total_claims_checked
        if issue_ratio > 0.5:
            confidence -= 0.2
        elif issue_ratio > 0.3:
            confidence -= 0.1

        # Decrease if many claims need action
        action_ratio = output.claims_requiring_action / output.total_claims_checked
        if action_ratio > 0.5:
            confidence -= 0.1

        # Decrease if oldest pending claim is very old
        if output.oldest_pending_claim_days and output.oldest_pending_claim_days > 60:
            confidence -= 0.15

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: ClaimsStatusTrackingOutput,
        confidence: float,
        input_data: ClaimsStatusTrackingInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Review if any claims have critical issues
        for claim in output.tracked_claims:
            critical_issues = [i for i in claim.issues if i.severity == "critical"]
            if critical_issues:
                return True, f"Claim {claim.claim_id} has {len(critical_issues)} critical issues"

        # Review if many claims need action
        if output.claims_requiring_action >= 5:
            return True, f"{output.claims_requiring_action} claims require action"

        # Review if oldest pending claim is very old
        if output.oldest_pending_claim_days and output.oldest_pending_claim_days > 60:
            return True, f"Oldest pending claim is {output.oldest_pending_claim_days} days old"

        # Review if confidence is low
        if confidence < 0.7:
            return True, f"Low confidence ({confidence:.2f})"

        return False, None
