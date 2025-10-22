"""
Referral Management Agent

Coordinates specialist referrals, tracks status, ensures clinical handoffs,
and monitors follow-through. Integrates with insurance verification for
authorization requirements.
"""

from datetime import datetime, timedelta
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

from platform_core.agents.base_agent import BaseAgent


# ============================================================================
# Input/Output Models
# ============================================================================


class ReferralUrgency(str, Enum):
    """Urgency level for referral"""
    EMERGENT = "emergent"  # Within 24 hours
    URGENT = "urgent"  # Within 1 week
    ROUTINE = "routine"  # Within 1 month
    NON_URGENT = "non_urgent"  # Within 3 months


class ReferralReason(BaseModel):
    """Reason for referral"""
    primary_diagnosis: str = Field(..., description="Primary diagnosis code (ICD-10)")
    diagnosis_description: str = Field(..., description="Diagnosis description")
    clinical_question: str = Field(..., description="Specific clinical question for specialist")
    relevant_history: str = Field(..., description="Relevant clinical history")
    previous_treatments: list[str] = Field(default_factory=list, description="Previous treatments attempted")


class ReferringProvider(BaseModel):
    """Information about referring provider"""
    provider_id: str
    name: str
    specialty: str
    npi: str
    contact_phone: str
    contact_email: str


class SpecialistPreferences(BaseModel):
    """Patient preferences for specialist"""
    preferred_gender: Optional[str] = None
    preferred_language: Optional[str] = None
    location_preference: Optional[str] = None
    max_distance_miles: Optional[float] = None
    accepts_new_patients_only: bool = True


class ReferralManagementInput(BaseModel):
    """Input for referral management"""
    patient_id: str
    patient_name: str
    patient_dob: str
    patient_insurance: dict[str, Any] = Field(..., description="Insurance information")

    referring_provider: ReferringProvider

    specialty_needed: str = Field(..., description="Specialty type needed")
    referral_reason: ReferralReason
    urgency: ReferralUrgency

    specialist_preferences: Optional[SpecialistPreferences] = None

    # Clinical documents to attach
    relevant_lab_results: list[dict[str, Any]] = Field(default_factory=list)
    relevant_imaging: list[dict[str, Any]] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)

    # Existing referral ID if tracking status
    referral_id: Optional[str] = None
    action: Literal["create", "track_status", "complete"] = "create"


class SpecialistMatch(BaseModel):
    """Matched specialist for referral"""
    specialist_id: str
    name: str
    specialty: str
    subspecialty: Optional[str] = None
    npi: str

    practice_name: str
    address: str
    phone: str
    fax: str

    accepts_insurance: bool
    accepting_new_patients: bool
    next_available_appointment: Optional[str] = None
    average_wait_time_days: Optional[int] = None

    distance_miles: Optional[float] = None
    match_score: float = Field(..., ge=0.0, le=1.0)
    match_reasons: list[str]


class AuthorizationRequirement(BaseModel):
    """Prior authorization requirements"""
    requires_prior_auth: bool
    auth_type: Optional[str] = None  # "pre_auth", "pre_certification", "referral_only"
    estimated_approval_time_days: Optional[int] = None
    approval_probability: float = Field(..., ge=0.0, le=1.0)
    documentation_needed: list[str] = Field(default_factory=list)
    submission_instructions: Optional[str] = None


class ReferralStatus(str, Enum):
    """Status of referral"""
    PENDING_AUTH = "pending_authorization"
    AUTH_APPROVED = "authorization_approved"
    AUTH_DENIED = "authorization_denied"
    SENT_TO_SPECIALIST = "sent_to_specialist"
    APPOINTMENT_SCHEDULED = "appointment_scheduled"
    APPOINTMENT_COMPLETED = "appointment_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReferralTracking(BaseModel):
    """Tracking information for referral"""
    referral_id: str
    status: ReferralStatus
    status_updated_at: str

    authorization_id: Optional[str] = None
    authorization_valid_until: Optional[str] = None

    specialist_name: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_completed: bool = False

    report_received: bool = False
    report_date: Optional[str] = None

    days_since_referral: int
    action_needed: Optional[str] = None
    action_due_date: Optional[str] = None


class ClinicalHandoff(BaseModel):
    """Clinical information for handoff"""
    referral_summary: str = Field(..., description="Summary for specialist")
    clinical_question: str
    relevant_findings: list[str]
    medications_to_review: list[str]
    documents_attached: list[str]
    urgency_note: Optional[str] = None


class ReferralManagementOutput(BaseModel):
    """Output from referral management"""
    success: bool
    referral_id: str

    # Matched specialists (for create action)
    recommended_specialists: list[SpecialistMatch] = Field(default_factory=list)

    # Authorization requirements
    authorization_required: AuthorizationRequirement

    # Generated clinical handoff
    clinical_handoff: Optional[ClinicalHandoff] = None

    # Tracking information
    tracking: Optional[ReferralTracking] = None

    # Next steps
    next_steps: list[str]
    estimated_timeline: str

    # Flags
    requires_urgent_attention: bool = False
    missing_information: list[str] = Field(default_factory=list)

    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool


# ============================================================================
# Agent Implementation
# ============================================================================


class ReferralManagementAgent(BaseAgent[ReferralManagementInput, ReferralManagementOutput]):
    """
    Coordinates specialist referrals and tracks their completion.

    Features:
    - Matches patients to appropriate specialists
    - Checks insurance authorization requirements
    - Generates clinical handoff documentation
    - Tracks referral status and completion
    - Monitors follow-through and flags delays

    Integration:
    - Insurance Verification Agent (for auth requirements)
    - Smart Scheduling Agent (for specialist matching)
    - Clinical Documentation Agent (for handoff notes)
    """

    def __init__(self, llm_provider: str = "anthropic"):
        super().__init__()
        self.llm_provider = llm_provider

        # Initialize LLM clients
        if llm_provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic
                import os
                self.anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            except ImportError:
                self.anthropic_client = None
        else:
            try:
                from openai import AsyncOpenAI
                import os
                self.openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            except ImportError:
                self.openai_client = None

    async def _execute_internal(
        self,
        input_data: ReferralManagementInput,
        context: dict[str, Any]
    ) -> ReferralManagementOutput:
        """Execute referral management workflow"""

        if input_data.action == "create":
            return await self._create_referral(input_data, context)
        elif input_data.action == "track_status":
            return await self._track_referral_status(input_data, context)
        elif input_data.action == "complete":
            return await self._complete_referral(input_data, context)
        else:
            raise ValueError(f"Unknown action: {input_data.action}")

    async def _create_referral(
        self,
        input_data: ReferralManagementInput,
        context: dict[str, Any]
    ) -> ReferralManagementOutput:
        """Create new referral"""

        # Step 1: Generate referral ID
        referral_id = f"REF-{input_data.patient_id[:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Step 2: Find matching specialists
        specialists = await self._find_matching_specialists(input_data)

        # Step 3: Check authorization requirements
        auth_requirements = await self._check_authorization_requirements(input_data)

        # Step 4: Generate clinical handoff documentation
        clinical_handoff = await self._generate_clinical_handoff(input_data)

        # Step 5: Determine next steps
        next_steps = self._determine_next_steps(input_data, auth_requirements, specialists)

        # Step 6: Calculate timeline
        timeline = self._calculate_timeline(input_data.urgency, auth_requirements)

        # Step 7: Check for missing information
        missing_info = self._check_missing_information(input_data)

        # Step 8: Calculate confidence
        confidence = self._calculate_confidence(specialists, auth_requirements, missing_info)

        return ReferralManagementOutput(
            success=True,
            referral_id=referral_id,
            recommended_specialists=specialists,
            authorization_required=auth_requirements,
            clinical_handoff=clinical_handoff,
            tracking=None,  # Will be created after specialist selected
            next_steps=next_steps,
            estimated_timeline=timeline,
            requires_urgent_attention=(input_data.urgency in [ReferralUrgency.EMERGENT, ReferralUrgency.URGENT]),
            missing_information=missing_info,
            confidence=confidence,
            needs_human_review=(confidence < 0.8 or len(missing_info) > 0)
        )

    async def _find_matching_specialists(
        self,
        input_data: ReferralManagementInput
    ) -> list[SpecialistMatch]:
        """Find specialists matching patient needs"""

        # In production, this would query a specialist directory database
        # For now, return mock specialists with realistic matching logic

        mock_specialists = [
            {
                "specialist_id": "SPEC001",
                "name": "Dr. Sarah Johnson",
                "specialty": input_data.specialty_needed,
                "subspecialty": "Advanced Care",
                "npi": "1234567890",
                "practice_name": "Central Medical Specialists",
                "address": "123 Medical Plaza, Suite 200",
                "phone": "(555) 123-4567",
                "fax": "(555) 123-4568",
                "accepts_insurance": True,
                "accepting_new_patients": True,
                "next_available": 7,  # days
                "distance": 2.3,
                "quality_rating": 4.8
            },
            {
                "specialist_id": "SPEC002",
                "name": "Dr. Michael Chen",
                "specialty": input_data.specialty_needed,
                "subspecialty": None,
                "npi": "0987654321",
                "practice_name": "University Health System",
                "address": "456 Hospital Drive",
                "phone": "(555) 234-5678",
                "fax": "(555) 234-5679",
                "accepts_insurance": True,
                "accepting_new_patients": True,
                "next_available": 14,  # days
                "distance": 5.7,
                "quality_rating": 4.9
            },
            {
                "specialist_id": "SPEC003",
                "name": "Dr. Emily Rodriguez",
                "specialty": input_data.specialty_needed,
                "subspecialty": "Complex Cases",
                "npi": "5555555555",
                "practice_name": "Advanced Specialty Care",
                "address": "789 Wellness Center",
                "phone": "(555) 345-6789",
                "fax": "(555) 345-6790",
                "accepts_insurance": True,
                "accepting_new_patients": True,
                "next_available": 21,  # days
                "distance": 12.1,
                "quality_rating": 5.0
            }
        ]

        specialists = []
        for spec in mock_specialists:
            score, reasons = self._score_specialist_match(spec, input_data)

            next_available_date = (datetime.now() + timedelta(days=spec["next_available"])).strftime("%Y-%m-%d")

            specialists.append(SpecialistMatch(
                specialist_id=spec["specialist_id"],
                name=spec["name"],
                specialty=spec["specialty"],
                subspecialty=spec["subspecialty"],
                npi=spec["npi"],
                practice_name=spec["practice_name"],
                address=spec["address"],
                phone=spec["phone"],
                fax=spec["fax"],
                accepts_insurance=spec["accepts_insurance"],
                accepting_new_patients=spec["accepting_new_patients"],
                next_available_appointment=next_available_date,
                average_wait_time_days=spec["next_available"],
                distance_miles=spec["distance"],
                match_score=score,
                match_reasons=reasons
            ))

        # Sort by match score
        specialists.sort(key=lambda x: x.match_score, reverse=True)

        return specialists

    def _score_specialist_match(
        self,
        specialist: dict[str, Any],
        input_data: ReferralManagementInput
    ) -> tuple[float, list[str]]:
        """Score how well specialist matches patient needs"""

        score = 0.0
        reasons = []
        max_score = 100.0

        # Factor 1: Insurance acceptance (30 points)
        if specialist["accepts_insurance"]:
            score += 30
            reasons.append("Accepts patient's insurance")

        # Factor 2: Accepting new patients (20 points)
        if specialist["accepting_new_patients"]:
            score += 20
            reasons.append("Accepting new patients")

        # Factor 3: Availability vs urgency (25 points)
        days_available = specialist["next_available"]
        urgency_thresholds = {
            ReferralUrgency.EMERGENT: 1,
            ReferralUrgency.URGENT: 7,
            ReferralUrgency.ROUTINE: 30,
            ReferralUrgency.NON_URGENT: 90
        }
        threshold = urgency_thresholds[input_data.urgency]

        if days_available <= threshold:
            score += 25
            reasons.append(f"Available within {threshold} days")
        elif days_available <= threshold * 1.5:
            score += 15
            reasons.append(f"Available within acceptable timeframe")
        else:
            score += 5

        # Factor 4: Distance (15 points)
        distance = specialist["distance"]
        prefs = input_data.specialist_preferences

        if prefs and prefs.max_distance_miles:
            if distance <= prefs.max_distance_miles:
                score += 15
                reasons.append(f"Within preferred distance ({distance:.1f} miles)")
            elif distance <= prefs.max_distance_miles * 1.5:
                score += 8
        else:
            # Default: prefer closer
            if distance <= 5:
                score += 15
                reasons.append(f"Conveniently located ({distance:.1f} miles)")
            elif distance <= 15:
                score += 10
            else:
                score += 5

        # Factor 5: Quality rating (10 points)
        quality = specialist.get("quality_rating", 4.0)
        score += (quality / 5.0) * 10
        if quality >= 4.5:
            reasons.append(f"Highly rated ({quality}/5.0)")

        # Normalize to 0-1
        normalized_score = min(score / max_score, 1.0)

        return normalized_score, reasons

    async def _check_authorization_requirements(
        self,
        input_data: ReferralManagementInput
    ) -> AuthorizationRequirement:
        """Check if prior authorization required"""

        # In production, this would integrate with Insurance Verification Agent
        # and query payer-specific requirements

        insurance_plan = input_data.patient_insurance.get("plan_type", "unknown").lower()
        specialty = input_data.specialty_needed.lower()

        # Common specialties that typically require auth
        high_auth_specialties = [
            "cardiology", "neurology", "oncology", "orthopedic surgery",
            "pain management", "psychiatry", "rheumatology", "surgery"
        ]

        requires_auth = (
            "hmo" in insurance_plan or
            "medicaid" in insurance_plan or
            any(s in specialty for s in high_auth_specialties)
        )

        if requires_auth:
            # Estimate approval probability based on diagnosis and urgency
            approval_prob = 0.85  # Base probability

            if input_data.urgency in [ReferralUrgency.EMERGENT, ReferralUrgency.URGENT]:
                approval_prob = 0.95  # Higher for urgent cases

            if len(input_data.referral_reason.previous_treatments) > 0:
                approval_prob = 0.90  # Higher if conservative treatments tried

            documentation = [
                "Clinical notes from referring provider",
                "Diagnosis code (ICD-10)",
                "Clinical rationale for referral"
            ]

            if input_data.referral_reason.previous_treatments:
                documentation.append("Documentation of previous treatments attempted")

            if input_data.relevant_lab_results:
                documentation.append("Supporting lab results")

            if input_data.relevant_imaging:
                documentation.append("Supporting imaging studies")

            return AuthorizationRequirement(
                requires_prior_auth=True,
                auth_type="pre_auth",
                estimated_approval_time_days=3 if input_data.urgency == ReferralUrgency.EMERGENT else 7,
                approval_probability=approval_prob,
                documentation_needed=documentation,
                submission_instructions="Submit via payer portal or fax to utilization management"
            )
        else:
            return AuthorizationRequirement(
                requires_prior_auth=False,
                auth_type="referral_only",
                estimated_approval_time_days=0,
                approval_probability=1.0,
                documentation_needed=[],
                submission_instructions="No prior authorization required. Referral can be sent directly."
            )

    async def _generate_clinical_handoff(
        self,
        input_data: ReferralManagementInput
    ) -> ClinicalHandoff:
        """Generate clinical handoff documentation for specialist"""

        # Use LLM to generate comprehensive handoff summary
        if self.llm_provider == "anthropic" and self.anthropic_client:
            summary = await self._generate_handoff_with_anthropic(input_data)
        elif self.llm_provider == "openai" and self.openai_client:
            summary = await self._generate_handoff_with_openai(input_data)
        else:
            # Fallback to template-based
            summary = self._generate_handoff_template(input_data)

        # Extract relevant findings
        findings = []
        if input_data.referral_reason.relevant_history:
            findings.append(input_data.referral_reason.relevant_history)

        if input_data.referral_reason.previous_treatments:
            findings.append(f"Previous treatments: {', '.join(input_data.referral_reason.previous_treatments)}")

        # Documents being attached
        documents = []
        if input_data.relevant_lab_results:
            documents.append(f"{len(input_data.relevant_lab_results)} lab result(s)")
        if input_data.relevant_imaging:
            documents.append(f"{len(input_data.relevant_imaging)} imaging study(ies)")
        documents.append("Current medication list")
        documents.append("Clinical notes from referring provider")

        # Urgency note
        urgency_note = None
        if input_data.urgency == ReferralUrgency.EMERGENT:
            urgency_note = "EMERGENT: This patient requires evaluation within 24 hours."
        elif input_data.urgency == ReferralUrgency.URGENT:
            urgency_note = "URGENT: This patient should be seen within 1 week."

        return ClinicalHandoff(
            referral_summary=summary,
            clinical_question=input_data.referral_reason.clinical_question,
            relevant_findings=findings,
            medications_to_review=input_data.current_medications,
            documents_attached=documents,
            urgency_note=urgency_note
        )

    async def _generate_handoff_with_anthropic(
        self,
        input_data: ReferralManagementInput
    ) -> str:
        """Generate handoff summary using Anthropic Claude"""

        prompt = f"""Generate a professional, concise clinical handoff summary for a specialist referral.

Patient: {input_data.patient_name}
DOB: {input_data.patient_dob}

Referring Provider: {input_data.referring_provider.name}, {input_data.referring_provider.specialty}

Specialty Needed: {input_data.specialty_needed}

Primary Diagnosis: {input_data.referral_reason.diagnosis_description} ({input_data.referral_reason.primary_diagnosis})

Clinical Question: {input_data.referral_reason.clinical_question}

Relevant History: {input_data.referral_reason.relevant_history}

Previous Treatments: {', '.join(input_data.referral_reason.previous_treatments) if input_data.referral_reason.previous_treatments else 'None documented'}

Current Medications: {', '.join(input_data.current_medications) if input_data.current_medications else 'See attached medication list'}

Urgency: {input_data.urgency.value}

Please write a 2-3 paragraph clinical summary suitable for the specialist to review. Focus on:
1. Chief complaint and clinical presentation
2. Relevant history and previous treatments
3. Specific reason for referral and clinical question

Keep it professional, concise, and clinically relevant."""

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=800,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}]
            )

            return response.content[0].text.strip()
        except Exception as e:
            # Fallback to template
            return self._generate_handoff_template(input_data)

    async def _generate_handoff_with_openai(
        self,
        input_data: ReferralManagementInput
    ) -> str:
        """Generate handoff summary using OpenAI"""

        prompt = f"""Generate a professional, concise clinical handoff summary for a specialist referral.

Patient: {input_data.patient_name}
DOB: {input_data.patient_dob}

Referring Provider: {input_data.referring_provider.name}, {input_data.referring_provider.specialty}

Specialty Needed: {input_data.specialty_needed}

Primary Diagnosis: {input_data.referral_reason.diagnosis_description} ({input_data.referral_reason.primary_diagnosis})

Clinical Question: {input_data.referral_reason.clinical_question}

Relevant History: {input_data.referral_reason.relevant_history}

Previous Treatments: {', '.join(input_data.referral_reason.previous_treatments) if input_data.referral_reason.previous_treatments else 'None documented'}

Current Medications: {', '.join(input_data.current_medications) if input_data.current_medications else 'See attached medication list'}

Urgency: {input_data.urgency.value}

Please write a 2-3 paragraph clinical summary suitable for the specialist to review."""

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            # Fallback to template
            return self._generate_handoff_template(input_data)

    def _generate_handoff_template(
        self,
        input_data: ReferralManagementInput
    ) -> str:
        """Generate handoff using template (fallback)"""

        summary = f"""REFERRAL SUMMARY

Patient {input_data.patient_name} is being referred to {input_data.specialty_needed} for evaluation of {input_data.referral_reason.diagnosis_description} ({input_data.referral_reason.primary_diagnosis}).

{input_data.referral_reason.relevant_history}

"""

        if input_data.referral_reason.previous_treatments:
            summary += f"Previous treatments include: {', '.join(input_data.referral_reason.previous_treatments)}. "

        summary += f"\nClinical Question: {input_data.referral_reason.clinical_question}\n"

        if input_data.current_medications:
            summary += f"\nCurrent medications: {', '.join(input_data.current_medications[:5])}"
            if len(input_data.current_medications) > 5:
                summary += f" (and {len(input_data.current_medications) - 5} more - see attached list)"

        return summary.strip()

    def _determine_next_steps(
        self,
        input_data: ReferralManagementInput,
        auth_req: AuthorizationRequirement,
        specialists: list[SpecialistMatch]
    ) -> list[str]:
        """Determine next steps for referral"""

        steps = []

        if not specialists:
            steps.append("⚠️ No matching specialists found - may need to expand search criteria")
            return steps

        steps.append(f"Review {len(specialists)} recommended specialists and select preferred provider")

        if auth_req.requires_prior_auth:
            steps.append(f"Submit prior authorization request with required documentation")
            steps.append(f"Estimated authorization approval time: {auth_req.estimated_approval_time_days} days")

        steps.append("Send referral documentation to selected specialist")
        steps.append("Coordinate appointment scheduling with patient")
        steps.append("Monitor referral completion and specialist report")

        if input_data.urgency in [ReferralUrgency.EMERGENT, ReferralUrgency.URGENT]:
            steps.insert(0, f"⚠️ {input_data.urgency.value.upper()} referral - expedite all steps")

        return steps

    def _calculate_timeline(
        self,
        urgency: ReferralUrgency,
        auth_req: AuthorizationRequirement
    ) -> str:
        """Calculate expected timeline for referral completion"""

        auth_days = auth_req.estimated_approval_time_days if auth_req.requires_prior_auth else 0

        urgency_targets = {
            ReferralUrgency.EMERGENT: 1,
            ReferralUrgency.URGENT: 7,
            ReferralUrgency.ROUTINE: 30,
            ReferralUrgency.NON_URGENT: 90
        }

        target_days = urgency_targets[urgency]
        total_days = auth_days + target_days

        if auth_req.requires_prior_auth:
            return f"Estimated {total_days} days total ({auth_days} days for authorization + {target_days} days to appointment)"
        else:
            return f"Estimated {target_days} days to appointment"

    def _check_missing_information(
        self,
        input_data: ReferralManagementInput
    ) -> list[str]:
        """Check for missing information that could delay referral"""

        missing = []

        if not input_data.current_medications:
            missing.append("Current medication list")

        if not input_data.referral_reason.previous_treatments:
            missing.append("Previous treatments attempted (may be required for authorization)")

        if not input_data.relevant_lab_results and not input_data.relevant_imaging:
            missing.append("Supporting diagnostic results (may strengthen authorization)")

        if not input_data.patient_insurance.get("member_id"):
            missing.append("Insurance member ID")

        if not input_data.patient_insurance.get("group_number"):
            missing.append("Insurance group number")

        return missing

    def _calculate_confidence(
        self,
        specialists: list[SpecialistMatch],
        auth_req: AuthorizationRequirement,
        missing_info: list[str]
    ) -> float:
        """Calculate confidence in referral coordination"""

        confidence = 1.0

        # Reduce confidence if no good specialist matches
        if not specialists:
            confidence -= 0.4
        elif specialists[0].match_score < 0.7:
            confidence -= 0.2

        # Reduce confidence if auth required with low approval probability
        if auth_req.requires_prior_auth and auth_req.approval_probability < 0.8:
            confidence -= 0.15

        # Reduce confidence for missing information
        confidence -= len(missing_info) * 0.05

        return max(confidence, 0.0)

    async def _track_referral_status(
        self,
        input_data: ReferralManagementInput,
        context: dict[str, Any]
    ) -> ReferralManagementOutput:
        """Track status of existing referral"""

        if not input_data.referral_id:
            raise ValueError("referral_id required for track_status action")

        # In production, this would query the referral tracking database
        # For now, return mock tracking data

        # Simulate referral created 10 days ago
        days_since = 10

        tracking = ReferralTracking(
            referral_id=input_data.referral_id,
            status=ReferralStatus.APPOINTMENT_SCHEDULED,
            status_updated_at=(datetime.now() - timedelta(days=2)).isoformat(),
            authorization_id="AUTH12345",
            authorization_valid_until=(datetime.now() + timedelta(days=80)).isoformat(),
            specialist_name="Dr. Sarah Johnson",
            appointment_date=(datetime.now() + timedelta(days=5)).isoformat(),
            appointment_completed=False,
            report_received=False,
            report_date=None,
            days_since_referral=days_since,
            action_needed="Patient appointment scheduled - no action needed",
            action_due_date=None
        )

        next_steps = [
            "Patient appointment scheduled for " + tracking.appointment_date,
            "Send appointment reminder to patient 24 hours before",
            "Follow up after appointment to obtain specialist report",
            "Update care plan based on specialist recommendations"
        ]

        return ReferralManagementOutput(
            success=True,
            referral_id=input_data.referral_id,
            recommended_specialists=[],
            authorization_required=AuthorizationRequirement(
                requires_prior_auth=True,
                approval_probability=1.0,
                documentation_needed=[]
            ),
            clinical_handoff=None,
            tracking=tracking,
            next_steps=next_steps,
            estimated_timeline=f"Appointment in 5 days",
            requires_urgent_attention=False,
            missing_information=[],
            confidence=0.95,
            needs_human_review=False
        )

    async def _complete_referral(
        self,
        input_data: ReferralManagementInput,
        context: dict[str, Any]
    ) -> ReferralManagementOutput:
        """Mark referral as completed and close loop"""

        if not input_data.referral_id:
            raise ValueError("referral_id required for complete action")

        # In production, this would update the referral in database
        # and trigger care plan updates

        tracking = ReferralTracking(
            referral_id=input_data.referral_id,
            status=ReferralStatus.COMPLETED,
            status_updated_at=datetime.now().isoformat(),
            authorization_id="AUTH12345",
            authorization_valid_until=(datetime.now() + timedelta(days=70)).isoformat(),
            specialist_name="Dr. Sarah Johnson",
            appointment_date=(datetime.now() - timedelta(days=2)).isoformat(),
            appointment_completed=True,
            report_received=True,
            report_date=datetime.now().isoformat(),
            days_since_referral=15,
            action_needed=None,
            action_due_date=None
        )

        next_steps = [
            "Referral completed successfully",
            "Review specialist report and recommendations",
            "Update patient care plan with specialist input",
            "Schedule follow-up with primary provider if recommended",
            "Close referral loop in EHR"
        ]

        return ReferralManagementOutput(
            success=True,
            referral_id=input_data.referral_id,
            recommended_specialists=[],
            authorization_required=AuthorizationRequirement(
                requires_prior_auth=False,
                approval_probability=1.0,
                documentation_needed=[]
            ),
            clinical_handoff=None,
            tracking=tracking,
            next_steps=next_steps,
            estimated_timeline="Completed",
            requires_urgent_attention=False,
            missing_information=[],
            confidence=1.0,
            needs_human_review=False
        )
