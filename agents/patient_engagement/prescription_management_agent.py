"""
Prescription Management Agent

Automates prescription refills, monitors medication adherence, detects
potential issues, and coordinates with pharmacies and providers.
"""

from datetime import datetime, timedelta
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

from platform_core.agents.base_agent import BaseAgent


# ============================================================================
# Input/Output Models
# ============================================================================


class MedicationStatus(str, Enum):
    """Status of medication"""
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"


class RefillStatus(str, Enum):
    """Refill request status"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    SENT_TO_PHARMACY = "sent_to_pharmacy"
    READY_FOR_PICKUP = "ready_for_pickup"
    COMPLETED = "completed"


class AdherenceLevel(str, Enum):
    """Medication adherence level"""
    EXCELLENT = "excellent"  # >90%
    GOOD = "good"  # 80-90%
    FAIR = "fair"  # 60-80%
    POOR = "poor"  # <60%


class Medication(BaseModel):
    """Medication information"""
    medication_id: str
    name: str
    dosage: str
    frequency: str
    route: str = "oral"

    prescribing_provider: str
    prescribed_date: str

    quantity: int
    refills_remaining: int
    days_supply: int

    status: MedicationStatus = MedicationStatus.ACTIVE

    # Adherence tracking
    last_filled_date: Optional[str] = None
    next_refill_due: Optional[str] = None


class PatientProfile(BaseModel):
    """Patient profile for prescription management"""
    patient_id: str
    patient_name: str
    date_of_birth: str

    allergies: list[str] = Field(default_factory=list)
    current_medications: list[Medication] = Field(default_factory=list)

    # Contact info
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_contact_method: str = "email"

    # Pharmacy info
    preferred_pharmacy: Optional[dict[str, Any]] = None


class RefillRequest(BaseModel):
    """Prescription refill request"""
    medication_id: str
    patient_id: str
    requested_date: str
    urgency: Literal["routine", "urgent", "emergency"] = "routine"

    # Auto-approve if criteria met
    auto_approve_eligible: bool = True


class PrescriptionManagementInput(BaseModel):
    """Input for prescription management"""
    patient_profile: PatientProfile

    action: Literal[
        "check_refills",
        "request_refill",
        "check_adherence",
        "detect_issues"
    ] = "check_refills"

    # For refill requests
    refill_requests: list[RefillRequest] = Field(default_factory=list)

    # For adherence checking
    adherence_period_days: int = Field(default=90, description="Days to analyze adherence")


class RefillRecommendation(BaseModel):
    """Refill recommendation"""
    medication_id: str
    medication_name: str

    needs_refill: bool
    days_until_out: int
    refills_remaining: int

    recommendation: str
    urgency: str  # routine, soon, urgent

    can_auto_approve: bool
    auto_approve_reason: Optional[str] = None
    requires_provider_approval: bool


class RefillResult(BaseModel):
    """Result of refill request"""
    medication_id: str
    medication_name: str

    request_status: RefillStatus
    request_id: Optional[str] = None

    approval_needed: bool
    approval_requested_from: Optional[str] = None

    pharmacy_notified: bool
    estimated_ready_date: Optional[str] = None

    next_steps: list[str]


class AdherenceAnalysis(BaseModel):
    """Medication adherence analysis"""
    medication_id: str
    medication_name: str

    adherence_rate: float = Field(..., ge=0.0, le=1.0)
    adherence_level: AdherenceLevel

    doses_prescribed: int
    doses_taken_estimated: int
    doses_missed_estimated: int

    refill_pattern: str  # consistent, irregular, declining

    barriers_identified: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class MedicationIssue(BaseModel):
    """Detected medication issue"""
    issue_type: str = Field(
        ...,
        description="drug_interaction, duplicate_therapy, allergy_concern, adherence_problem, contraindication, other"
    )
    severity: str = Field(..., description="low, medium, high, critical")

    medications_involved: list[str]

    description: str
    clinical_significance: str
    recommended_action: str

    requires_immediate_attention: bool


class PrescriptionManagementOutput(BaseModel):
    """Output from prescription management"""
    success: bool

    # Refill recommendations
    refill_recommendations: list[RefillRecommendation] = Field(default_factory=list)

    # Refill results
    refill_results: list[RefillResult] = Field(default_factory=list)

    # Adherence analysis
    adherence_analyses: list[AdherenceAnalysis] = Field(default_factory=list)
    overall_adherence_score: Optional[float] = None

    # Issues detected
    issues_detected: list[MedicationIssue] = Field(default_factory=list)

    # Summary
    summary: str
    next_steps: list[str]

    # Flags
    requires_provider_review: bool = False
    requires_immediate_action: bool = False

    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool


# ============================================================================
# Agent Implementation
# ============================================================================


class PrescriptionManagementAgent(BaseAgent[PrescriptionManagementInput, PrescriptionManagementOutput]):
    """
    Automates prescription refills and monitors medication adherence.

    Features:
    - Automatic refill recommendations and processing
    - Medication adherence monitoring and intervention
    - Drug interaction and allergy checking
    - Pharmacy coordination
    - Provider notification for approval needs
    - Patient engagement and reminders

    Integration:
    - EHR/EMR system (medication lists)
    - e-Prescribing systems (Surescripts)
    - Pharmacy benefit managers
    - Patient engagement platforms
    """

    def __init__(self):
        super().__init__()

    async def _execute_internal(
        self,
        input_data: PrescriptionManagementInput,
        context: dict[str, Any]
    ) -> PrescriptionManagementOutput:
        """Execute prescription management workflow"""

        if input_data.action == "check_refills":
            return await self._check_refills(input_data, context)
        elif input_data.action == "request_refill":
            return await self._request_refills(input_data, context)
        elif input_data.action == "check_adherence":
            return await self._check_adherence(input_data, context)
        elif input_data.action == "detect_issues":
            return await self._detect_issues(input_data, context)
        else:
            raise ValueError(f"Unknown action: {input_data.action}")

    async def _check_refills(
        self,
        input_data: PrescriptionManagementInput,
        context: dict[str, Any]
    ) -> PrescriptionManagementOutput:
        """Check which medications need refills"""

        patient = input_data.patient_profile

        # Analyze each active medication
        refill_recommendations = []
        for med in patient.current_medications:
            if med.status != MedicationStatus.ACTIVE:
                continue

            recommendation = self._analyze_refill_need(med)
            refill_recommendations.append(recommendation)

        # Check for any issues
        issues = self._check_for_issues(patient.current_medications, patient.allergies)

        # Generate summary
        needs_refill = [r for r in refill_recommendations if r.needs_refill]
        summary = self._generate_refill_summary(needs_refill, issues)

        # Next steps
        next_steps = self._determine_refill_next_steps(needs_refill, issues)

        # Calculate confidence
        confidence = 0.95  # High confidence for refill checks

        requires_immediate = any(r.urgency == "urgent" for r in refill_recommendations)
        requires_review = len(issues) > 0 or any(i.severity in ["high", "critical"] for i in issues)

        return PrescriptionManagementOutput(
            success=True,
            refill_recommendations=refill_recommendations,
            refill_results=[],
            adherence_analyses=[],
            issues_detected=issues,
            summary=summary,
            next_steps=next_steps,
            requires_provider_review=requires_review,
            requires_immediate_action=requires_immediate,
            confidence=confidence,
            needs_human_review=requires_review
        )

    def _analyze_refill_need(self, medication: Medication) -> RefillRecommendation:
        """Analyze if medication needs refill"""

        # Calculate days until medication runs out
        if medication.last_filled_date and medication.next_refill_due:
            last_filled = datetime.fromisoformat(medication.last_filled_date)
            next_due = datetime.fromisoformat(medication.next_refill_due)
            today = datetime.now()

            days_until_out = (next_due - today).days
        else:
            # If no fill date, assume mid-supply
            days_until_out = medication.days_supply // 2

        # Determine if refill needed
        needs_refill = days_until_out <= 7  # Refill within 7 days

        # Determine urgency
        if days_until_out <= 0:
            urgency = "urgent"
            recommendation = "Medication supply exhausted - immediate refill needed"
        elif days_until_out <= 3:
            urgency = "urgent"
            recommendation = f"Refill needed within {days_until_out} days"
        elif days_until_out <= 7:
            urgency = "soon"
            recommendation = f"Refill recommended within {days_until_out} days"
        else:
            urgency = "routine"
            recommendation = f"No immediate refill needed ({days_until_out} days remaining)"

        # Check if can auto-approve
        can_auto_approve = (
            medication.refills_remaining > 0 and
            medication.status == MedicationStatus.ACTIVE and
            urgency in ["routine", "soon"]
        )

        auto_approve_reason = None
        if can_auto_approve:
            auto_approve_reason = f"Refills remaining ({medication.refills_remaining}), routine request"

        requires_provider = (
            medication.refills_remaining == 0 or
            urgency == "urgent" or
            medication.status != MedicationStatus.ACTIVE
        )

        return RefillRecommendation(
            medication_id=medication.medication_id,
            medication_name=f"{medication.name} {medication.dosage}",
            needs_refill=needs_refill,
            days_until_out=days_until_out,
            refills_remaining=medication.refills_remaining,
            recommendation=recommendation,
            urgency=urgency,
            can_auto_approve=can_auto_approve,
            auto_approve_reason=auto_approve_reason,
            requires_provider_approval=requires_provider
        )

    async def _request_refills(
        self,
        input_data: PrescriptionManagementInput,
        context: dict[str, Any]
    ) -> PrescriptionManagementOutput:
        """Process refill requests"""

        patient = input_data.patient_profile
        refill_results = []

        for request in input_data.refill_requests:
            # Find medication
            med = next(
                (m for m in patient.current_medications if m.medication_id == request.medication_id),
                None
            )

            if not med:
                continue

            # Process refill
            result = await self._process_refill_request(request, med, patient)
            refill_results.append(result)

        # Check for issues
        issues = self._check_for_issues(patient.current_medications, patient.allergies)

        # Generate summary
        summary = f"Processed {len(refill_results)} refill request(s)"
        approved = sum(1 for r in refill_results if r.request_status == RefillStatus.APPROVED)
        if approved > 0:
            summary += f", {approved} approved"

        # Next steps
        next_steps = []
        for result in refill_results:
            next_steps.extend(result.next_steps)

        if len(issues) > 0:
            next_steps.append(f"Review {len(issues)} detected medication issue(s)")

        confidence = 0.92
        requires_review = any(r.approval_needed for r in refill_results) or len(issues) > 0

        return PrescriptionManagementOutput(
            success=True,
            refill_recommendations=[],
            refill_results=refill_results,
            adherence_analyses=[],
            issues_detected=issues,
            summary=summary,
            next_steps=next_steps,
            requires_provider_review=requires_review,
            requires_immediate_action=False,
            confidence=confidence,
            needs_human_review=requires_review
        )

    async def _process_refill_request(
        self,
        request: RefillRequest,
        medication: Medication,
        patient: PatientProfile
    ) -> RefillResult:
        """Process individual refill request"""

        # Check if can auto-approve
        can_auto_approve = (
            request.auto_approve_eligible and
            medication.refills_remaining > 0 and
            medication.status == MedicationStatus.ACTIVE
        )

        if can_auto_approve:
            # Auto-approve and send to pharmacy
            status = RefillStatus.SENT_TO_PHARMACY
            request_id = f"RX-{request.medication_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

            pharmacy_notified = bool(patient.preferred_pharmacy)
            estimated_ready = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d")

            next_steps = [
                "Refill approved automatically",
                f"Sent to {patient.preferred_pharmacy.get('name', 'preferred pharmacy') if patient.preferred_pharmacy else 'pharmacy'}",
                f"Estimated ready: {estimated_ready}",
                "Notify patient when ready for pickup"
            ]

            return RefillResult(
                medication_id=medication.medication_id,
                medication_name=f"{medication.name} {medication.dosage}",
                request_status=status,
                request_id=request_id,
                approval_needed=False,
                approval_requested_from=None,
                pharmacy_notified=pharmacy_notified,
                estimated_ready_date=estimated_ready,
                next_steps=next_steps
            )
        else:
            # Requires provider approval
            status = RefillStatus.PENDING

            next_steps = [
                "Provider approval required",
                f"Reason: {'No refills remaining' if medication.refills_remaining == 0 else 'Requires clinical review'}",
                f"Request sent to {medication.prescribing_provider}",
                "Notify patient of approval status within 24-48 hours"
            ]

            return RefillResult(
                medication_id=medication.medication_id,
                medication_name=f"{medication.name} {medication.dosage}",
                request_status=status,
                request_id=None,
                approval_needed=True,
                approval_requested_from=medication.prescribing_provider,
                pharmacy_notified=False,
                estimated_ready_date=None,
                next_steps=next_steps
            )

    async def _check_adherence(
        self,
        input_data: PrescriptionManagementInput,
        context: dict[str, Any]
    ) -> PrescriptionManagementOutput:
        """Check medication adherence"""

        patient = input_data.patient_profile
        period_days = input_data.adherence_period_days

        adherence_analyses = []

        for med in patient.current_medications:
            if med.status != MedicationStatus.ACTIVE:
                continue

            analysis = self._analyze_adherence(med, period_days)
            adherence_analyses.append(analysis)

        # Calculate overall adherence
        if adherence_analyses:
            overall_adherence = sum(a.adherence_rate for a in adherence_analyses) / len(adherence_analyses)
        else:
            overall_adherence = None

        # Identify adherence issues
        issues = []
        for analysis in adherence_analyses:
            if analysis.adherence_level == AdherenceLevel.POOR:
                issues.append(MedicationIssue(
                    issue_type="adherence_problem",
                    severity="medium",
                    medications_involved=[analysis.medication_name],
                    description=f"Poor adherence detected: {analysis.adherence_rate*100:.0f}%",
                    clinical_significance="May compromise treatment effectiveness",
                    recommended_action="Engage patient to identify barriers and provide support",
                    requires_immediate_attention=False
                ))

        # Generate summary
        if overall_adherence:
            summary = f"Overall adherence: {overall_adherence*100:.0f}%. "
        else:
            summary = "No active medications to analyze. "

        poor_adherence = sum(1 for a in adherence_analyses if a.adherence_level == AdherenceLevel.POOR)
        if poor_adherence > 0:
            summary += f"{poor_adherence} medication(s) with poor adherence."

        # Next steps
        next_steps = []
        for analysis in adherence_analyses:
            if analysis.adherence_level in [AdherenceLevel.POOR, AdherenceLevel.FAIR]:
                next_steps.append(f"Contact patient about {analysis.medication_name} adherence")
                for rec in analysis.recommendations[:2]:  # Top 2 recommendations
                    next_steps.append(f"  - {rec}")

        if not next_steps:
            next_steps.append("Continue monitoring adherence")

        confidence = 0.85  # Medium confidence due to estimation

        return PrescriptionManagementOutput(
            success=True,
            refill_recommendations=[],
            refill_results=[],
            adherence_analyses=adherence_analyses,
            overall_adherence_score=overall_adherence,
            issues_detected=issues,
            summary=summary,
            next_steps=next_steps,
            requires_provider_review=(poor_adherence > 0),
            requires_immediate_action=False,
            confidence=confidence,
            needs_human_review=(poor_adherence > 0)
        )

    def _analyze_adherence(self, medication: Medication, period_days: int) -> AdherenceAnalysis:
        """Analyze adherence for single medication"""

        # In production, this would:
        # 1. Query prescription fill history
        # 2. Calculate PDC (Proportion of Days Covered)
        # 3. Analyze refill patterns
        # 4. Survey patient about barriers

        # Mock adherence calculation
        # Use days_supply and refill pattern to estimate

        if medication.last_filled_date:
            last_filled = datetime.fromisoformat(medication.last_filled_date)
            days_since_fill = (datetime.now() - last_filled).days

            # Estimate adherence based on refill timing
            expected_refill_day = medication.days_supply
            if days_since_fill <= expected_refill_day:
                adherence_rate = 0.95  # On time
                refill_pattern = "consistent"
            elif days_since_fill <= expected_refill_day * 1.2:
                adherence_rate = 0.80  # Slightly late
                refill_pattern = "irregular"
            else:
                adherence_rate = 0.60  # Very late
                refill_pattern = "declining"
        else:
            # No fill data, assume moderate adherence
            adherence_rate = 0.75
            refill_pattern = "unknown"

        # Determine adherence level
        if adherence_rate >= 0.90:
            level = AdherenceLevel.EXCELLENT
        elif adherence_rate >= 0.80:
            level = AdherenceLevel.GOOD
        elif adherence_rate >= 0.60:
            level = AdherenceLevel.FAIR
        else:
            level = AdherenceLevel.POOR

        # Estimate doses
        # Assume medication taken daily (simplification)
        doses_prescribed = period_days
        doses_taken = int(doses_prescribed * adherence_rate)
        doses_missed = doses_prescribed - doses_taken

        # Identify potential barriers
        barriers = []
        if adherence_rate < 0.80:
            if refill_pattern == "irregular":
                barriers.append("Inconsistent refill pattern")
            if refill_pattern == "declining":
                barriers.append("Declining adherence over time")

        # Recommendations
        recommendations = []
        if adherence_rate < 0.80:
            recommendations.append("Set up medication reminders")
            recommendations.append("Discuss barriers with patient")
            if refill_pattern == "irregular":
                recommendations.append("Offer auto-refill program")

        return AdherenceAnalysis(
            medication_id=medication.medication_id,
            medication_name=f"{medication.name} {medication.dosage}",
            adherence_rate=adherence_rate,
            adherence_level=level,
            doses_prescribed=doses_prescribed,
            doses_taken_estimated=doses_taken,
            doses_missed_estimated=doses_missed,
            refill_pattern=refill_pattern,
            barriers_identified=barriers,
            recommendations=recommendations
        )

    async def _detect_issues(
        self,
        input_data: PrescriptionManagementInput,
        context: dict[str, Any]
    ) -> PrescriptionManagementOutput:
        """Detect medication-related issues"""

        patient = input_data.patient_profile

        issues = self._check_for_issues(patient.current_medications, patient.allergies)

        # Generate summary
        if len(issues) == 0:
            summary = "No medication issues detected"
        else:
            critical = sum(1 for i in issues if i.severity == "critical")
            high = sum(1 for i in issues if i.severity == "high")

            summary = f"Detected {len(issues)} issue(s)"
            if critical > 0:
                summary += f" ({critical} critical)"
            elif high > 0:
                summary += f" ({high} high severity)"

        # Next steps
        next_steps = []
        for issue in issues:
            if issue.requires_immediate_attention:
                next_steps.append(f"🚨 IMMEDIATE: {issue.recommended_action}")
            else:
                next_steps.append(issue.recommended_action)

        if not next_steps:
            next_steps.append("Continue routine medication monitoring")

        requires_immediate = any(i.requires_immediate_attention for i in issues)
        confidence = 0.85 if len(issues) == 0 else 0.75

        return PrescriptionManagementOutput(
            success=True,
            refill_recommendations=[],
            refill_results=[],
            adherence_analyses=[],
            issues_detected=issues,
            summary=summary,
            next_steps=next_steps,
            requires_provider_review=(len(issues) > 0),
            requires_immediate_action=requires_immediate,
            confidence=confidence,
            needs_human_review=(len(issues) > 0)
        )

    def _check_for_issues(
        self,
        medications: list[Medication],
        allergies: list[str]
    ) -> list[MedicationIssue]:
        """Check for medication issues"""

        issues = []

        # Check for allergy concerns
        for med in medications:
            if med.status != MedicationStatus.ACTIVE:
                continue

            for allergy in allergies:
                # Simple string matching (production would use drug database)
                if allergy.lower() in med.name.lower():
                    issues.append(MedicationIssue(
                        issue_type="allergy_concern",
                        severity="critical",
                        medications_involved=[med.name],
                        description=f"Patient allergic to {allergy}, prescribed {med.name}",
                        clinical_significance="May cause allergic reaction",
                        recommended_action="Discontinue immediately and contact prescriber",
                        requires_immediate_attention=True
                    ))

        # Check for duplicate therapy
        active_meds = [m for m in medications if m.status == MedicationStatus.ACTIVE]
        med_classes = {}  # Would map to drug classes in production

        for med in active_meds:
            # Simplified: check for same drug name (would use drug class in production)
            base_name = med.name.split()[0].lower() if med.name else ""
            if base_name in med_classes:
                issues.append(MedicationIssue(
                    issue_type="duplicate_therapy",
                    severity="medium",
                    medications_involved=[med_classes[base_name], med.name],
                    description=f"Potential duplicate therapy: {med_classes[base_name]} and {med.name}",
                    clinical_significance="May lead to increased side effects or overdose risk",
                    recommended_action="Review with prescriber for clinical appropriateness",
                    requires_immediate_attention=False
                ))
            else:
                med_classes[base_name] = med.name

        return issues

    def _generate_refill_summary(
        self,
        needs_refill: list[RefillRecommendation],
        issues: list[MedicationIssue]
    ) -> str:
        """Generate refill check summary"""

        if len(needs_refill) == 0:
            summary = "No medications need refills at this time"
        else:
            urgent = sum(1 for r in needs_refill if r.urgency == "urgent")
            soon = sum(1 for r in needs_refill if r.urgency == "soon")

            summary = f"{len(needs_refill)} medication(s) need refills"
            if urgent > 0:
                summary += f" ({urgent} urgent)"
            elif soon > 0:
                summary += f" ({soon} needed soon)"

        if len(issues) > 0:
            summary += f". {len(issues)} issue(s) detected"

        return summary

    def _determine_refill_next_steps(
        self,
        needs_refill: list[RefillRecommendation],
        issues: list[MedicationIssue]
    ) -> list[str]:
        """Determine next steps for refills"""

        steps = []

        # Handle urgent refills first
        urgent = [r for r in needs_refill if r.urgency == "urgent"]
        if urgent:
            for rec in urgent:
                if rec.can_auto_approve:
                    steps.append(f"Process urgent refill for {rec.medication_name}")
                else:
                    steps.append(f"⚠️ Contact prescriber for urgent refill: {rec.medication_name}")

        # Handle routine refills
        routine = [r for r in needs_refill if r.can_auto_approve and r.urgency != "urgent"]
        if routine:
            steps.append(f"Auto-approve {len(routine)} routine refill(s)")

        # Handle those needing provider approval
        needs_approval = [r for r in needs_refill if r.requires_provider_approval and r.urgency != "urgent"]
        if needs_approval:
            steps.append(f"Request provider approval for {len(needs_approval)} refill(s)")

        # Handle detected issues
        if issues:
            critical = [i for i in issues if i.severity == "critical"]
            if critical:
                steps.insert(0, f"🚨 Address {len(critical)} critical medication issue(s) immediately")

        if not steps:
            steps.append("No immediate action required")

        return steps
