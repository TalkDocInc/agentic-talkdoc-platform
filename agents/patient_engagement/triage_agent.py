"""
Triage Agent

Performs intelligent symptom assessment, determines care urgency, and routes
patients to appropriate care levels with safety-first algorithms.
"""

from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

from platform_core.agents.base_agent import BaseAgent


# ============================================================================
# Input/Output Models
# ============================================================================


class CareUrgency(str, Enum):
    """Care urgency level"""
    EMERGENCY = "emergency"  # 911 / ER immediately
    URGENT = "urgent"  # Same-day care required
    PROMPT = "prompt"  # Care within 24-48 hours
    ROUTINE = "routine"  # Schedule regular appointment
    SELF_CARE = "self_care"  # Self-care with monitoring


class Symptom(BaseModel):
    """Individual symptom"""
    symptom: str
    severity: int = Field(..., ge=1, le=10, description="Severity 1-10")
    duration_hours: Optional[int] = None
    onset: str = Field(..., description="sudden, gradual, or chronic")

    # Red flag indicators
    worsening: bool = False
    affecting_daily_activities: bool = False


class PatientContext(BaseModel):
    """Patient context for triage"""
    patient_id: str
    age: int
    sex: str

    # Medical history
    chronic_conditions: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)

    # Vital signs if available
    temperature_f: Optional[float] = None
    heart_rate: Optional[int] = None
    blood_pressure_systolic: Optional[int] = None
    blood_pressure_diastolic: Optional[int] = None
    respiratory_rate: Optional[int] = None
    oxygen_saturation: Optional[int] = None

    # Risk factors
    pregnant: Optional[bool] = None
    immunocompromised: Optional[bool] = None


class TriageInput(BaseModel):
    """Input for triage assessment"""
    patient_context: PatientContext

    chief_complaint: str = Field(..., description="Main reason for seeking care")
    symptoms: list[Symptom]

    # Additional context
    recent_injuries: list[str] = Field(default_factory=list)
    recent_exposures: list[str] = Field(default_factory=list)

    # LLM provider for assessment
    llm_provider: str = Field(default="anthropic")


class RedFlag(BaseModel):
    """Red flag warning"""
    flag_type: str
    description: str
    recommendation: str
    severity: str = Field(..., description="critical, high, medium")


class DifferentialDiagnosis(BaseModel):
    """Potential diagnosis"""
    condition: str
    probability: float = Field(..., ge=0.0, le=1.0)
    supporting_symptoms: list[str]
    key_differentiators: list[str]


class CareRecommendation(BaseModel):
    """Recommended care pathway"""
    urgency: CareUrgency
    care_level: str = Field(..., description="emergency_department, urgent_care, primary_care, telehealth, self_care")

    timeframe: str
    rationale: str

    # Instructions
    immediate_actions: list[str]
    warning_signs: list[str]
    self_care_instructions: Optional[str] = None


class SafetyAssessment(BaseModel):
    """Safety and suicide risk assessment"""
    requires_immediate_intervention: bool
    suicide_risk_level: str = Field(..., description="none, low, moderate, high, imminent")

    risk_factors: list[str] = Field(default_factory=list)
    protective_factors: list[str] = Field(default_factory=list)

    crisis_resources: Optional[str] = None


class TriageOutput(BaseModel):
    """Output from triage assessment"""
    success: bool
    triage_id: str
    assessment_date: str

    # Assessment results
    care_recommendation: CareRecommendation
    differential_diagnoses: list[DifferentialDiagnosis] = Field(default_factory=list)

    # Safety
    red_flags: list[RedFlag] = Field(default_factory=list)
    safety_assessment: Optional[SafetyAssessment] = None

    # Clinical summary
    clinical_summary: str
    triage_notes: str

    # Follow-up
    requires_provider_callback: bool
    estimated_wait_time: Optional[str] = None

    # Next steps
    next_steps: list[str]
    patient_instructions: str

    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool


# ============================================================================
# Agent Implementation
# ============================================================================


class TriageAgent(BaseAgent[TriageInput, TriageOutput]):
    """
    Performs intelligent symptom assessment and care routing.

    Features:
    - Symptom severity assessment using clinical algorithms
    - Red flag detection for emergency conditions
    - Differential diagnosis generation
    - Care urgency determination
    - Safety-first routing with escalation
    - Mental health crisis detection
    - Evidence-based triage protocols

    Integration:
    - Smart Scheduling Agent (route to appropriate providers)
    - AI Health Advisor (continuity for self-care cases)
    - Clinical Documentation Agent (triage notes in chart)
    - Emergency services (911 dispatch if needed)
    """

    # Emergency red flag keywords
    EMERGENCY_KEYWORDS = [
        "chest pain", "crushing", "radiating", "shortness of breath", "severe",
        "can't breathe", "stroke", "paralysis", "slurred speech", "confusion",
        "severe bleeding", "uncontrolled", "head injury", "unconscious",
        "seizure", "overdose", "poisoning", "severe burn",
        "suicidal", "kill myself", "end my life", "suicide plan"
    ]

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
        input_data: TriageInput,
        context: dict[str, Any]
    ) -> TriageOutput:
        """Execute triage assessment workflow"""

        triage_id = f"TRIAGE-{input_data.patient_context.patient_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Step 1: Immediate safety check (red flags)
        red_flags = self._detect_red_flags(input_data)

        # Step 2: Safety assessment (suicide risk)
        safety_assessment = self._assess_safety(input_data)

        # Step 3: Vital signs assessment if available
        vitals_concerning = self._assess_vital_signs(input_data.patient_context)

        # Step 4: Determine care urgency
        care_recommendation = await self._determine_care_urgency(
            input_data,
            red_flags,
            safety_assessment,
            vitals_concerning
        )

        # Step 5: Generate differential diagnoses
        differential_dx = await self._generate_differential_diagnoses(input_data)

        # Step 6: Generate clinical summary
        clinical_summary = self._generate_clinical_summary(input_data, care_recommendation)

        # Step 7: Generate triage notes
        triage_notes = self._generate_triage_notes(
            input_data,
            care_recommendation,
            red_flags,
            differential_dx
        )

        # Step 8: Generate patient instructions
        patient_instructions = self._generate_patient_instructions(care_recommendation)

        # Step 9: Determine next steps
        next_steps = self._determine_next_steps(
            care_recommendation,
            red_flags,
            safety_assessment
        )

        # Step 10: Calculate confidence
        confidence = self._calculate_confidence(
            input_data,
            red_flags,
            care_recommendation
        )

        requires_callback = (
            care_recommendation.urgency in [CareUrgency.EMERGENCY, CareUrgency.URGENT] or
            len(red_flags) > 0 or
            (safety_assessment and safety_assessment.suicide_risk_level in ["high", "imminent"])
        )

        return TriageOutput(
            success=True,
            triage_id=triage_id,
            assessment_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            care_recommendation=care_recommendation,
            differential_diagnoses=differential_dx,
            red_flags=red_flags,
            safety_assessment=safety_assessment,
            clinical_summary=clinical_summary,
            triage_notes=triage_notes,
            requires_provider_callback=requires_callback,
            estimated_wait_time=self._estimate_wait_time(care_recommendation),
            next_steps=next_steps,
            patient_instructions=patient_instructions,
            confidence=confidence,
            needs_human_review=(len(red_flags) > 0 or requires_callback)
        )

    def _detect_red_flags(self, input_data: TriageInput) -> list[RedFlag]:
        """Detect emergency red flags"""

        red_flags = []

        complaint_lower = input_data.chief_complaint.lower()
        all_symptoms = " ".join([s.symptom.lower() for s in input_data.symptoms])
        combined_text = complaint_lower + " " + all_symptoms

        # Check for emergency keywords
        for keyword in self.EMERGENCY_KEYWORDS:
            if keyword in combined_text:
                red_flags.append(RedFlag(
                    flag_type="emergency_symptom",
                    description=f"Emergency keyword detected: '{keyword}'",
                    recommendation="Immediate emergency evaluation required - call 911",
                    severity="critical"
                ))
                break  # One emergency flag is enough

        # Check for chest pain red flags
        if any(term in combined_text for term in ["chest pain", "chest pressure", "chest tightness"]):
            # Check for cardiac red flags
            cardiac_flags = ["radiating", "arm", "jaw", "shortness of breath", "sweating", "nausea"]
            if any(flag in combined_text for flag in cardiac_flags):
                red_flags.append(RedFlag(
                    flag_type="cardiac_emergency",
                    description="Chest pain with cardiac warning signs",
                    recommendation="Call 911 immediately - possible heart attack",
                    severity="critical"
                ))

        # Check for stroke red flags (FAST)
        stroke_indicators = ["facial drooping", "arm weakness", "slurred speech", "sudden confusion"]
        if any(indicator in combined_text for indicator in stroke_indicators):
            red_flags.append(RedFlag(
                flag_type="stroke_warning",
                description="Stroke warning signs detected",
                recommendation="Call 911 immediately - time is critical for stroke",
                severity="critical"
            ))

        # Check for severe pain
        severe_symptoms = [s for s in input_data.symptoms if s.severity >= 8]
        if severe_symptoms:
            for symptom in severe_symptoms:
                red_flags.append(RedFlag(
                    flag_type="severe_pain",
                    description=f"Severe {symptom.symptom} (severity {symptom.severity}/10)",
                    recommendation="Urgent medical evaluation required",
                    severity="high"
                ))

        # Check for high-risk patient groups
        if input_data.patient_context.pregnant and "bleeding" in combined_text:
            red_flags.append(RedFlag(
                flag_type="pregnancy_emergency",
                description="Bleeding during pregnancy",
                recommendation="Immediate OB/GYN evaluation required",
                severity="critical"
            ))

        # Check for immunocompromised with fever
        if input_data.patient_context.immunocompromised:
            temp = input_data.patient_context.temperature_f
            if temp and temp >= 100.4:
                red_flags.append(RedFlag(
                    flag_type="immunocompromised_fever",
                    description="Fever in immunocompromised patient",
                    recommendation="Same-day medical evaluation required",
                    severity="high"
                ))

        return red_flags

    def _assess_safety(self, input_data: TriageInput) -> Optional[SafetyAssessment]:
        """Assess suicide risk"""

        complaint_lower = input_data.chief_complaint.lower()
        all_symptoms = " ".join([s.symptom.lower() for s in input_data.symptoms])
        combined_text = complaint_lower + " " + all_symptoms

        # Check for suicide keywords
        suicide_keywords = [
            "suicide", "suicidal", "kill myself", "end my life",
            "want to die", "better off dead", "suicide plan"
        ]

        has_suicide_ideation = any(keyword in combined_text for keyword in suicide_keywords)

        if not has_suicide_ideation:
            # Quick mental health screening
            if any(term in combined_text for term in ["depression", "hopeless", "worthless"]):
                return SafetyAssessment(
                    requires_immediate_intervention=False,
                    suicide_risk_level="low",
                    risk_factors=["Depressive symptoms present"],
                    protective_factors=[],
                    crisis_resources=None
                )
            return None

        # Suicide ideation detected - assess severity
        has_plan = any(term in combined_text for term in ["plan", "method", "how to"])
        has_intent = any(term in combined_text for term in ["going to", "will", "tonight", "soon"])

        if has_plan and has_intent:
            risk_level = "imminent"
        elif has_plan or has_intent:
            risk_level = "high"
        else:
            risk_level = "moderate"

        crisis_resources = """
🚨 IMMEDIATE HELP AVAILABLE:

• 988 Suicide & Crisis Lifeline: Call or text 988 (24/7)
• Crisis Text Line: Text HOME to 741741
• Emergency: Call 911
• Do not leave patient alone
"""

        return SafetyAssessment(
            requires_immediate_intervention=(risk_level in ["high", "imminent"]),
            suicide_risk_level=risk_level,
            risk_factors=[
                "Active suicidal ideation",
                "Suicide plan" if has_plan else None,
                "Expressed intent" if has_intent else None
            ],
            protective_factors=[],  # Would be assessed in full evaluation
            crisis_resources=crisis_resources
        )

    def _assess_vital_signs(self, patient_context: PatientContext) -> bool:
        """Assess if vital signs are concerning"""

        concerning = False

        # Temperature
        if patient_context.temperature_f:
            if patient_context.temperature_f >= 103.0 or patient_context.temperature_f <= 95.0:
                concerning = True

        # Heart rate
        if patient_context.heart_rate:
            if patient_context.heart_rate >= 120 or patient_context.heart_rate <= 50:
                concerning = True

        # Blood pressure
        if patient_context.blood_pressure_systolic:
            if patient_context.blood_pressure_systolic >= 180 or patient_context.blood_pressure_systolic <= 90:
                concerning = True

        # Oxygen saturation
        if patient_context.oxygen_saturation:
            if patient_context.oxygen_saturation <= 92:
                concerning = True

        # Respiratory rate
        if patient_context.respiratory_rate:
            if patient_context.respiratory_rate >= 24 or patient_context.respiratory_rate <= 10:
                concerning = True

        return concerning

    async def _determine_care_urgency(
        self,
        input_data: TriageInput,
        red_flags: list[RedFlag],
        safety_assessment: Optional[SafetyAssessment],
        vitals_concerning: bool
    ) -> CareRecommendation:
        """Determine appropriate care urgency and level"""

        # Emergency conditions
        if any(flag.severity == "critical" for flag in red_flags):
            return CareRecommendation(
                urgency=CareUrgency.EMERGENCY,
                care_level="emergency_department",
                timeframe="IMMEDIATELY - Call 911",
                rationale="Life-threatening symptoms detected requiring immediate emergency care",
                immediate_actions=[
                    "Call 911 or go to nearest emergency department immediately",
                    "Do not drive yourself - call ambulance",
                    "Bring list of current medications"
                ],
                warning_signs=[
                    "Symptoms worsen",
                    "Loss of consciousness",
                    "Severe difficulty breathing"
                ],
                self_care_instructions=None
            )

        # Imminent suicide risk
        if safety_assessment and safety_assessment.suicide_risk_level == "imminent":
            return CareRecommendation(
                urgency=CareUrgency.EMERGENCY,
                care_level="emergency_department",
                timeframe="IMMEDIATELY",
                rationale="Imminent suicide risk requires immediate intervention",
                immediate_actions=[
                    "Call 988 Suicide & Crisis Lifeline or 911",
                    "Do not leave person alone",
                    "Remove access to lethal means",
                    "Go to nearest emergency department"
                ],
                warning_signs=[],
                self_care_instructions=None
            )

        # High urgency
        if (any(flag.severity == "high" for flag in red_flags) or
            vitals_concerning or
            (safety_assessment and safety_assessment.suicide_risk_level == "high")):
            return CareRecommendation(
                urgency=CareUrgency.URGENT,
                care_level="urgent_care",
                timeframe="Same day (within 4-8 hours)",
                rationale="Urgent medical evaluation required",
                immediate_actions=[
                    "Schedule urgent care or same-day appointment",
                    "Go to urgent care if appointment not available",
                    "Monitor symptoms closely"
                ],
                warning_signs=[
                    "Symptoms rapidly worsen",
                    "New severe symptoms develop",
                    "Unable to manage pain"
                ],
                self_care_instructions=None
            )

        # Check severity scores
        max_severity = max([s.severity for s in input_data.symptoms], default=0)

        if max_severity >= 7:
            return CareRecommendation(
                urgency=CareUrgency.URGENT,
                care_level="primary_care",
                timeframe="Within 24 hours",
                rationale="Moderate to severe symptoms requiring medical evaluation",
                immediate_actions=[
                    "Contact primary care provider for same-day or next-day appointment",
                    "If unavailable, visit urgent care",
                    "Take over-the-counter medications as appropriate"
                ],
                warning_signs=[
                    "Fever above 103°F",
                    "Symptoms significantly worsen",
                    "Unable to keep fluids down"
                ],
                self_care_instructions="Rest, stay hydrated, monitor temperature"
            )

        elif max_severity >= 5:
            return CareRecommendation(
                urgency=CareUrgency.PROMPT,
                care_level="telehealth",
                timeframe="Within 24-48 hours",
                rationale="Symptoms warrant medical evaluation within 1-2 days",
                immediate_actions=[
                    "Schedule appointment with primary care or telehealth visit",
                    "Begin symptom tracking",
                    "Use appropriate over-the-counter medications"
                ],
                warning_signs=[
                    "Symptoms persist beyond 3-5 days",
                    "Fever develops or worsens",
                    "New concerning symptoms appear"
                ],
                self_care_instructions="Rest, fluids, over-the-counter symptom relief as appropriate"
            )

        else:
            return CareRecommendation(
                urgency=CareUrgency.ROUTINE,
                care_level="telehealth",
                timeframe="Routine appointment (1-2 weeks)",
                rationale="Mild symptoms that can be managed with self-care and routine follow-up",
                immediate_actions=[
                    "Schedule routine appointment if symptoms persist",
                    "Begin self-care measures",
                    "Monitor for changes"
                ],
                warning_signs=[
                    "Symptoms worsen or don't improve in 7-10 days",
                    "New symptoms develop",
                    "Fever or severe pain develops"
                ],
                self_care_instructions="Continue self-care, rest, stay hydrated, monitor symptoms"
            )

    async def _generate_differential_diagnoses(
        self,
        input_data: TriageInput
    ) -> list[DifferentialDiagnosis]:
        """Generate potential diagnoses"""

        # In production, this would use medical knowledge bases and ML models
        # For now, basic pattern matching

        differentials = []

        complaint_lower = input_data.chief_complaint.lower()
        symptom_text = " ".join([s.symptom.lower() for s in input_data.symptoms])
        combined = complaint_lower + " " + symptom_text

        # Common patterns (simplified for demo)
        if any(term in combined for term in ["fever", "cough", "congestion"]):
            differentials.append(DifferentialDiagnosis(
                condition="Upper Respiratory Infection",
                probability=0.75,
                supporting_symptoms=["fever", "cough", "congestion"],
                key_differentiators=["Duration < 10 days", "Gradual onset"]
            ))

        if "headache" in combined:
            differentials.append(DifferentialDiagnosis(
                condition="Tension Headache",
                probability=0.60,
                supporting_symptoms=["headache", "stress"],
                key_differentiators=["Bilateral", "Band-like pressure"]
            ))

        return differentials[:3]  # Return top 3

    def _generate_clinical_summary(
        self,
        input_data: TriageInput,
        care_rec: CareRecommendation
    ) -> str:
        """Generate clinical summary for triage"""

        patient = input_data.patient_context

        summary_parts = [
            f"Patient: {patient.age}yo {patient.sex}",
            f"Chief Complaint: {input_data.chief_complaint}",
            f"Symptoms: {', '.join([f'{s.symptom} (severity {s.severity}/10)' for s in input_data.symptoms[:3]])}",
        ]

        if patient.chronic_conditions:
            summary_parts.append(f"PMH: {', '.join(patient.chronic_conditions)}")

        if patient.temperature_f:
            summary_parts.append(f"Temp: {patient.temperature_f}°F")

        summary_parts.append(f"Triage Level: {care_rec.urgency.value.upper()}")

        return " | ".join(summary_parts)

    def _generate_triage_notes(
        self,
        input_data: TriageInput,
        care_rec: CareRecommendation,
        red_flags: list[RedFlag],
        differentials: list[DifferentialDiagnosis]
    ) -> str:
        """Generate detailed triage notes"""

        notes = []

        notes.append(f"TRIAGE ASSESSMENT - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        notes.append("")
        notes.append(f"Chief Complaint: {input_data.chief_complaint}")
        notes.append("")

        notes.append("Symptoms:")
        for symptom in input_data.symptoms:
            notes.append(f"  - {symptom.symptom}: {symptom.severity}/10, {symptom.onset} onset")
        notes.append("")

        if red_flags:
            notes.append("⚠️ RED FLAGS:")
            for flag in red_flags:
                notes.append(f"  - {flag.description}")
            notes.append("")

        notes.append(f"Triage Level: {care_rec.urgency.value.upper()}")
        notes.append(f"Recommended Care: {care_rec.care_level}")
        notes.append(f"Timeframe: {care_rec.timeframe}")
        notes.append("")

        if differentials:
            notes.append("Differential Diagnoses:")
            for dx in differentials:
                notes.append(f"  - {dx.condition} ({dx.probability*100:.0f}% probability)")

        return "\n".join(notes)

    def _generate_patient_instructions(self, care_rec: CareRecommendation) -> str:
        """Generate patient-facing instructions"""

        instructions = []

        instructions.append(f"Based on your symptoms, you should: {care_rec.timeframe}")
        instructions.append("")

        instructions.append("What to do now:")
        for action in care_rec.immediate_actions:
            instructions.append(f"• {action}")
        instructions.append("")

        instructions.append("Seek immediate care if you experience:")
        for warning in care_rec.warning_signs:
            instructions.append(f"⚠️ {warning}")

        if care_rec.self_care_instructions:
            instructions.append("")
            instructions.append("Self-care:")
            instructions.append(care_rec.self_care_instructions)

        return "\n".join(instructions)

    def _determine_next_steps(
        self,
        care_rec: CareRecommendation,
        red_flags: list[RedFlag],
        safety_assessment: Optional[SafetyAssessment]
    ) -> list[str]:
        """Determine system next steps"""

        steps = []

        if care_rec.urgency == CareUrgency.EMERGENCY:
            steps.append("🚨 CRITICAL: Immediate provider notification")
            steps.append("Provide patient with 911 instructions")
            steps.append("Document emergency triage in medical record")
        elif care_rec.urgency == CareUrgency.URGENT:
            steps.append("Notify care team for same-day scheduling")
            steps.append("Send urgent care instructions to patient")
            steps.append("Schedule provider callback within 1 hour")
        else:
            steps.append("Send care instructions to patient")
            steps.append("Offer scheduling options based on urgency")
            steps.append("Add to provider review queue")

        if safety_assessment and safety_assessment.suicide_risk_level in ["high", "imminent"]:
            steps.insert(0, "🚨 CRISIS: Immediate mental health crisis intervention")
            steps.insert(1, "Contact emergency services and crisis team")

        steps.append("Log triage assessment in audit trail")

        return steps

    def _estimate_wait_time(self, care_rec: CareRecommendation) -> Optional[str]:
        """Estimate wait time for care"""

        wait_times = {
            CareUrgency.EMERGENCY: "Immediate",
            CareUrgency.URGENT: "2-4 hours",
            CareUrgency.PROMPT: "24-48 hours",
            CareUrgency.ROUTINE: "1-2 weeks",
            CareUrgency.SELF_CARE: "N/A"
        }

        return wait_times.get(care_rec.urgency)

    def _calculate_confidence(
        self,
        input_data: TriageInput,
        red_flags: list[RedFlag],
        care_rec: CareRecommendation
    ) -> float:
        """Calculate confidence in triage assessment"""

        confidence = 1.0

        # High confidence for emergency cases (safety first)
        if red_flags:
            return 0.95  # High confidence in emergency detection

        # Reduce confidence if limited information
        if not input_data.patient_context.chronic_conditions:
            confidence -= 0.05

        if len(input_data.symptoms) < 2:
            confidence -= 0.10

        # Reduce confidence if no vital signs for urgent cases
        if care_rec.urgency == CareUrgency.URGENT:
            if not input_data.patient_context.temperature_f:
                confidence -= 0.10

        return max(confidence, 0.70)
