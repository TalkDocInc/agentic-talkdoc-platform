"""
Lab Results Processing Agent

Automates lab result interpretation, abnormal value flagging, clinical significance
assessment, and patient notification with provider escalation.
"""

from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

from platform_core.agents.base_agent import BaseAgent


# ============================================================================
# Input/Output Models
# ============================================================================


class ResultStatus(str, Enum):
    """Lab result status"""
    NORMAL = "normal"
    ABNORMAL_LOW = "abnormal_low"
    ABNORMAL_HIGH = "abnormal_high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"
    INDETERMINATE = "indeterminate"


class Urgency(str, Enum):
    """Clinical urgency level"""
    ROUTINE = "routine"  # Review within 1 week
    PROMPT = "prompt"  # Review within 24-48 hours
    URGENT = "urgent"  # Review within 4-8 hours
    CRITICAL = "critical"  # Immediate review required


class LabTest(BaseModel):
    """Individual lab test result"""
    test_code: str = Field(..., description="LOINC code")
    test_name: str
    result_value: float
    unit: str

    reference_range_low: Optional[float] = None
    reference_range_high: Optional[float] = None

    critical_low: Optional[float] = None
    critical_high: Optional[float] = None

    collection_date: str
    result_date: str


class PatientInfo(BaseModel):
    """Patient information for context"""
    patient_id: str
    patient_name: str
    age: int
    sex: str

    # Clinical context
    active_diagnoses: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)

    # Contact info
    email: Optional[str] = None
    phone: Optional[str] = None
    preferred_contact_method: str = "email"


class OrderingProvider(BaseModel):
    """Provider who ordered the tests"""
    provider_id: str
    provider_name: str
    specialty: str
    contact_email: str
    contact_phone: str


class LabResultsProcessingInput(BaseModel):
    """Input for lab results processing"""
    order_id: str
    patient_info: PatientInfo
    ordering_provider: OrderingProvider

    lab_tests: list[LabTest]

    # Processing options
    auto_notify_patient: bool = Field(default=True, description="Automatically send patient notification")
    notify_provider_on_abnormal: bool = Field(default=True, description="Notify provider of abnormal results")
    generate_patient_explanation: bool = Field(default=True, description="Generate patient-friendly explanation")

    # LLM provider for explanations
    llm_provider: str = Field(default="anthropic", description="LLM provider for generating explanations")


class LabResult(BaseModel):
    """Processed lab result"""
    test_code: str
    test_name: str
    result_value: float
    unit: str

    status: ResultStatus
    is_abnormal: bool
    is_critical: bool

    reference_range: str
    deviation_percent: Optional[float] = None

    clinical_significance: str
    patient_explanation: str


class AbnormalFinding(BaseModel):
    """Abnormal lab finding requiring attention"""
    test_name: str
    result_value: float
    unit: str
    status: ResultStatus
    urgency: Urgency

    clinical_implications: list[str]
    recommended_actions: list[str]

    related_diagnoses: list[str] = Field(default_factory=list)
    related_medications: list[str] = Field(default_factory=list)


class PatientNotification(BaseModel):
    """Notification for patient"""
    notification_id: str
    delivery_method: str  # email, sms, portal

    subject: str
    message: str

    includes_abnormal_results: bool
    requires_followup: bool
    followup_instructions: Optional[str] = None


class ProviderAlert(BaseModel):
    """Alert for ordering provider"""
    alert_id: str
    urgency: Urgency

    summary: str
    abnormal_findings_count: int
    critical_findings_count: int

    recommended_actions: list[str]
    requires_immediate_action: bool


class LabResultsProcessingOutput(BaseModel):
    """Output from lab results processing"""
    success: bool
    order_id: str
    processed_date: str

    # Processed results
    lab_results: list[LabResult]

    # Summary statistics
    total_tests: int
    normal_tests: int
    abnormal_tests: int
    critical_tests: int

    # Abnormal findings
    abnormal_findings: list[AbnormalFinding] = Field(default_factory=list)
    overall_urgency: Urgency

    # Notifications
    patient_notification: Optional[PatientNotification] = None
    provider_alert: Optional[ProviderAlert] = None

    # Next steps
    next_steps: list[str]
    requires_immediate_provider_review: bool

    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool


# ============================================================================
# Agent Implementation
# ============================================================================


class LabResultsProcessingAgent(BaseAgent[LabResultsProcessingInput, LabResultsProcessingOutput]):
    """
    Automates lab result interpretation and patient notification.

    Features:
    - Automatic result interpretation against reference ranges
    - Abnormal and critical value detection
    - Clinical significance assessment
    - Patient-friendly explanations (LLM-powered)
    - Urgency-based provider alerts
    - Multi-channel patient notifications
    - Integration with care plans

    Integration:
    - EHR/LIS systems (lab results)
    - Clinical Documentation Agent (add to notes)
    - Care Plan Management Agent (update goals based on results)
    - Patient engagement platform (notifications)
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
        input_data: LabResultsProcessingInput,
        context: dict[str, Any]
    ) -> LabResultsProcessingOutput:
        """Execute lab results processing workflow"""

        # Step 1: Process each lab test
        lab_results = []
        for test in input_data.lab_tests:
            result = await self._process_lab_test(test, input_data.patient_info)
            lab_results.append(result)

        # Step 2: Identify abnormal findings
        abnormal_findings = await self._identify_abnormal_findings(
            lab_results,
            input_data.patient_info,
            input_data.lab_tests
        )

        # Step 3: Determine overall urgency
        overall_urgency = self._determine_overall_urgency(abnormal_findings)

        # Step 4: Generate patient notification
        patient_notification = None
        if input_data.auto_notify_patient:
            patient_notification = await self._generate_patient_notification(
                lab_results,
                abnormal_findings,
                input_data.patient_info
            )

        # Step 5: Generate provider alert if needed
        provider_alert = None
        if input_data.notify_provider_on_abnormal and len(abnormal_findings) > 0:
            provider_alert = self._generate_provider_alert(
                abnormal_findings,
                overall_urgency,
                input_data.ordering_provider
            )

        # Step 6: Determine next steps
        next_steps = self._determine_next_steps(
            abnormal_findings,
            overall_urgency,
            patient_notification,
            provider_alert
        )

        # Step 7: Calculate statistics
        total_tests = len(lab_results)
        normal_tests = sum(1 for r in lab_results if r.status == ResultStatus.NORMAL)
        abnormal_tests = sum(1 for r in lab_results if r.is_abnormal and not r.is_critical)
        critical_tests = sum(1 for r in lab_results if r.is_critical)

        # Step 8: Calculate confidence
        confidence = self._calculate_confidence(lab_results, abnormal_findings)

        requires_immediate = overall_urgency == Urgency.CRITICAL

        return LabResultsProcessingOutput(
            success=True,
            order_id=input_data.order_id,
            processed_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lab_results=lab_results,
            total_tests=total_tests,
            normal_tests=normal_tests,
            abnormal_tests=abnormal_tests,
            critical_tests=critical_tests,
            abnormal_findings=abnormal_findings,
            overall_urgency=overall_urgency,
            patient_notification=patient_notification,
            provider_alert=provider_alert,
            next_steps=next_steps,
            requires_immediate_provider_review=requires_immediate,
            confidence=confidence,
            needs_human_review=(len(abnormal_findings) > 0 or requires_immediate)
        )

    async def _process_lab_test(
        self,
        test: LabTest,
        patient_info: PatientInfo
    ) -> LabResult:
        """Process individual lab test"""

        # Determine status
        status = self._determine_test_status(test)

        # Check if abnormal or critical
        is_abnormal = status not in [ResultStatus.NORMAL, ResultStatus.INDETERMINATE]
        is_critical = status in [ResultStatus.CRITICAL_LOW, ResultStatus.CRITICAL_HIGH]

        # Format reference range
        if test.reference_range_low is not None and test.reference_range_high is not None:
            reference_range = f"{test.reference_range_low}-{test.reference_range_high} {test.unit}"
        else:
            reference_range = "Not specified"

        # Calculate deviation percentage
        deviation_percent = None
        if test.reference_range_low is not None and test.reference_range_high is not None:
            mid_point = (test.reference_range_low + test.reference_range_high) / 2
            if mid_point > 0:
                deviation_percent = ((test.result_value - mid_point) / mid_point) * 100

        # Generate clinical significance
        clinical_significance = self._assess_clinical_significance(test, status, patient_info)

        # Generate patient-friendly explanation
        patient_explanation = self._generate_basic_explanation(test, status)

        return LabResult(
            test_code=test.test_code,
            test_name=test.test_name,
            result_value=test.result_value,
            unit=test.unit,
            status=status,
            is_abnormal=is_abnormal,
            is_critical=is_critical,
            reference_range=reference_range,
            deviation_percent=deviation_percent,
            clinical_significance=clinical_significance,
            patient_explanation=patient_explanation
        )

    def _determine_test_status(self, test: LabTest) -> ResultStatus:
        """Determine test result status"""

        # Check critical ranges first
        if test.critical_low is not None and test.result_value <= test.critical_low:
            return ResultStatus.CRITICAL_LOW
        if test.critical_high is not None and test.result_value >= test.critical_high:
            return ResultStatus.CRITICAL_HIGH

        # Check abnormal ranges
        if test.reference_range_low is not None and test.result_value < test.reference_range_low:
            return ResultStatus.ABNORMAL_LOW
        if test.reference_range_high is not None and test.result_value > test.reference_range_high:
            return ResultStatus.ABNORMAL_HIGH

        # Normal range
        if test.reference_range_low is not None and test.reference_range_high is not None:
            if test.reference_range_low <= test.result_value <= test.reference_range_high:
                return ResultStatus.NORMAL

        # If no reference ranges provided
        return ResultStatus.INDETERMINATE

    def _assess_clinical_significance(
        self,
        test: LabTest,
        status: ResultStatus,
        patient_info: PatientInfo
    ) -> str:
        """Assess clinical significance of result"""

        if status == ResultStatus.NORMAL:
            return "Within normal limits"

        # Basic assessments based on common tests
        test_name_lower = test.test_name.lower()

        if status in [ResultStatus.CRITICAL_LOW, ResultStatus.CRITICAL_HIGH]:
            return "CRITICAL: Requires immediate clinical attention"

        # Common test interpretations
        if "glucose" in test_name_lower:
            if status == ResultStatus.ABNORMAL_HIGH:
                return "Elevated - May indicate diabetes or prediabetes"
            elif status == ResultStatus.ABNORMAL_LOW:
                return "Low - May indicate hypoglycemia"

        elif "hemoglobin" in test_name_lower or "hgb" in test_name_lower:
            if status == ResultStatus.ABNORMAL_LOW:
                return "Low - May indicate anemia"
            elif status == ResultStatus.ABNORMAL_HIGH:
                return "Elevated - May indicate dehydration or polycythemia"

        elif "creatinine" in test_name_lower:
            if status == ResultStatus.ABNORMAL_HIGH:
                return "Elevated - May indicate impaired kidney function"

        elif "cholesterol" in test_name_lower or "ldl" in test_name_lower:
            if status == ResultStatus.ABNORMAL_HIGH:
                return "Elevated - May increase cardiovascular risk"

        # Generic assessments
        if status == ResultStatus.ABNORMAL_LOW:
            return "Below normal range - Clinical correlation recommended"
        elif status == ResultStatus.ABNORMAL_HIGH:
            return "Above normal range - Clinical correlation recommended"

        return "Requires clinical interpretation"

    def _generate_basic_explanation(self, test: LabTest, status: ResultStatus) -> str:
        """Generate basic patient-friendly explanation"""

        if status == ResultStatus.NORMAL:
            return f"Your {test.test_name} result is within the normal range."

        if status in [ResultStatus.CRITICAL_LOW, ResultStatus.CRITICAL_HIGH]:
            return f"Your {test.test_name} result requires urgent medical attention. Your provider will contact you immediately."

        if status == ResultStatus.ABNORMAL_LOW:
            return f"Your {test.test_name} result is lower than the normal range. Your provider will review this result and discuss any necessary next steps."

        if status == ResultStatus.ABNORMAL_HIGH:
            return f"Your {test.test_name} result is higher than the normal range. Your provider will review this result and discuss any necessary next steps."

        return f"Your {test.test_name} result is available. Your provider will review and discuss with you."

    async def _identify_abnormal_findings(
        self,
        lab_results: list[LabResult],
        patient_info: PatientInfo,
        lab_tests: list[LabTest]
    ) -> list[AbnormalFinding]:
        """Identify and categorize abnormal findings"""

        findings = []

        for result in lab_results:
            if not result.is_abnormal:
                continue

            # Determine urgency
            if result.is_critical:
                urgency = Urgency.CRITICAL
            elif abs(result.deviation_percent) > 50 if result.deviation_percent else False:
                urgency = Urgency.URGENT
            elif result.status in [ResultStatus.ABNORMAL_LOW, ResultStatus.ABNORMAL_HIGH]:
                urgency = Urgency.PROMPT
            else:
                urgency = Urgency.ROUTINE

            # Generate clinical implications
            implications = self._generate_clinical_implications(result, patient_info)

            # Generate recommended actions
            actions = self._generate_recommended_actions(result, urgency)

            # Find related diagnoses and medications
            related_dx = self._find_related_diagnoses(result, patient_info.active_diagnoses)
            related_meds = self._find_related_medications(result, patient_info.current_medications)

            finding = AbnormalFinding(
                test_name=result.test_name,
                result_value=result.result_value,
                unit=result.unit,
                status=result.status,
                urgency=urgency,
                clinical_implications=implications,
                recommended_actions=actions,
                related_diagnoses=related_dx,
                related_medications=related_meds
            )

            findings.append(finding)

        return findings

    def _generate_clinical_implications(
        self,
        result: LabResult,
        patient_info: PatientInfo
    ) -> list[str]:
        """Generate clinical implications of abnormal result"""

        implications = []

        # Add the basic clinical significance
        implications.append(result.clinical_significance)

        # Add context-specific implications
        test_name_lower = result.test_name.lower()

        if "glucose" in test_name_lower and result.status == ResultStatus.ABNORMAL_HIGH:
            if any("diabetes" in dx.lower() for dx in patient_info.active_diagnoses):
                implications.append("May indicate suboptimal diabetes control")

        if result.is_critical:
            implications.append("Requires immediate intervention to prevent complications")

        return implications

    def _generate_recommended_actions(
        self,
        result: LabResult,
        urgency: Urgency
    ) -> list[str]:
        """Generate recommended actions for abnormal result"""

        actions = []

        if urgency == Urgency.CRITICAL:
            actions.append("Contact patient immediately")
            actions.append("Consider emergency department referral if symptomatic")
            actions.append("Recheck laboratory values")
        elif urgency == Urgency.URGENT:
            actions.append("Review result with patient within 24 hours")
            actions.append("Consider medication adjustment")
            actions.append("Repeat testing in 1-2 weeks")
        elif urgency == Urgency.PROMPT:
            actions.append("Schedule follow-up appointment")
            actions.append("Review medications and lifestyle factors")
            actions.append("Consider repeat testing in 1-3 months")
        else:  # ROUTINE
            actions.append("Discuss at next scheduled appointment")
            actions.append("Consider trending over time")

        return actions

    def _find_related_diagnoses(
        self,
        result: LabResult,
        active_diagnoses: list[str]
    ) -> list[str]:
        """Find diagnoses related to abnormal result"""

        related = []
        test_name_lower = result.test_name.lower()

        for dx in active_diagnoses:
            dx_lower = dx.lower()

            # Simple keyword matching (production would use medical ontologies)
            if "glucose" in test_name_lower and "diabetes" in dx_lower:
                related.append(dx)
            elif "hemoglobin" in test_name_lower and "anemia" in dx_lower:
                related.append(dx)
            elif "creatinine" in test_name_lower and ("kidney" in dx_lower or "renal" in dx_lower):
                related.append(dx)

        return related

    def _find_related_medications(
        self,
        result: LabResult,
        current_medications: list[str]
    ) -> list[str]:
        """Find medications that may affect result"""

        related = []
        test_name_lower = result.test_name.lower()

        for med in current_medications:
            med_lower = med.lower()

            # Simple keyword matching
            if "glucose" in test_name_lower and any(term in med_lower for term in ["metformin", "insulin", "glipizide"]):
                related.append(med)
            elif "potassium" in test_name_lower and any(term in med_lower for term in ["lisinopril", "spironolactone"]):
                related.append(med)

        return related

    def _determine_overall_urgency(
        self,
        abnormal_findings: list[AbnormalFinding]
    ) -> Urgency:
        """Determine overall urgency level"""

        if not abnormal_findings:
            return Urgency.ROUTINE

        # Return highest urgency level
        urgencies = [f.urgency for f in abnormal_findings]

        if Urgency.CRITICAL in urgencies:
            return Urgency.CRITICAL
        elif Urgency.URGENT in urgencies:
            return Urgency.URGENT
        elif Urgency.PROMPT in urgencies:
            return Urgency.PROMPT
        else:
            return Urgency.ROUTINE

    async def _generate_patient_notification(
        self,
        lab_results: list[LabResult],
        abnormal_findings: list[AbnormalFinding],
        patient_info: PatientInfo
    ) -> PatientNotification:
        """Generate patient notification"""

        notification_id = f"NOTIF-{patient_info.patient_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        has_abnormal = len(abnormal_findings) > 0
        has_critical = any(f.urgency == Urgency.CRITICAL for f in abnormal_findings)

        # Generate subject
        if has_critical:
            subject = "URGENT: Your Lab Results Require Immediate Attention"
        elif has_abnormal:
            subject = "Your Lab Results Are Ready - Follow-up Needed"
        else:
            subject = "Your Lab Results Are Ready"

        # Generate message
        message_parts = [f"Dear {patient_info.patient_name},", ""]

        if has_critical:
            message_parts.append("Your recent lab results show values that require immediate medical attention. Your healthcare provider will be contacting you shortly. If you are experiencing any symptoms, please contact your provider immediately or go to the nearest emergency department.")
        elif has_abnormal:
            message_parts.append("Your recent lab results are ready. Some values are outside the normal range and require follow-up with your healthcare provider.")
        else:
            message_parts.append("Your recent lab results are ready. All values are within normal limits.")

        message_parts.append("")
        message_parts.append("Result Summary:")

        # Add result summaries
        for result in lab_results[:10]:  # Limit to first 10 for brevity
            status_emoji = "✅" if result.status == ResultStatus.NORMAL else "⚠️"
            message_parts.append(f"{status_emoji} {result.test_name}: {result.result_value} {result.unit}")

        if len(lab_results) > 10:
            message_parts.append(f"... and {len(lab_results) - 10} more test(s)")

        message_parts.append("")

        # Add follow-up instructions
        followup_instructions = None
        if has_critical:
            message_parts.append("Next Steps: Your provider will contact you immediately. Please be available by phone.")
            followup_instructions = "Await immediate provider contact"
        elif has_abnormal:
            message_parts.append("Next Steps: Please schedule a follow-up appointment with your provider to discuss these results.")
            followup_instructions = "Schedule follow-up appointment"
        else:
            message_parts.append("Next Steps: No immediate action needed. Results will be discussed at your next scheduled appointment.")

        message_parts.append("")
        message_parts.append("You can view your complete results in your patient portal.")
        message_parts.append("")
        message_parts.append("If you have any questions or concerns, please contact your provider's office.")

        message = "\n".join(message_parts)

        return PatientNotification(
            notification_id=notification_id,
            delivery_method=patient_info.preferred_contact_method,
            subject=subject,
            message=message,
            includes_abnormal_results=has_abnormal,
            requires_followup=(has_abnormal or has_critical),
            followup_instructions=followup_instructions
        )

    def _generate_provider_alert(
        self,
        abnormal_findings: list[AbnormalFinding],
        overall_urgency: Urgency,
        ordering_provider: OrderingProvider
    ) -> ProviderAlert:
        """Generate provider alert for abnormal results"""

        alert_id = f"ALERT-{ordering_provider.provider_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        critical_count = sum(1 for f in abnormal_findings if f.urgency == Urgency.CRITICAL)
        abnormal_count = len(abnormal_findings)

        # Generate summary
        if critical_count > 0:
            summary = f"CRITICAL: {critical_count} critical lab value(s) detected"
        else:
            summary = f"{abnormal_count} abnormal lab value(s) requiring review"

        # Compile recommended actions
        all_actions = set()
        for finding in abnormal_findings:
            all_actions.update(finding.recommended_actions)

        recommended_actions = list(all_actions)

        return ProviderAlert(
            alert_id=alert_id,
            urgency=overall_urgency,
            summary=summary,
            abnormal_findings_count=abnormal_count,
            critical_findings_count=critical_count,
            recommended_actions=recommended_actions,
            requires_immediate_action=(overall_urgency == Urgency.CRITICAL)
        )

    def _determine_next_steps(
        self,
        abnormal_findings: list[AbnormalFinding],
        overall_urgency: Urgency,
        patient_notification: Optional[PatientNotification],
        provider_alert: Optional[ProviderAlert]
    ) -> list[str]:
        """Determine next steps for lab results"""

        steps = []

        if overall_urgency == Urgency.CRITICAL:
            steps.append("🚨 CRITICAL: Contact provider immediately")
            steps.append("Alert patient via phone call")
            steps.append("Document in patient chart with high priority flag")
        elif len(abnormal_findings) > 0:
            steps.append(f"Notify provider of {len(abnormal_findings)} abnormal finding(s)")
            steps.append("Schedule follow-up appointment")

        if patient_notification:
            steps.append(f"Send patient notification via {patient_notification.delivery_method}")

        if provider_alert:
            steps.append(f"Send provider alert to {provider_alert.alert_id}")

        steps.append("Update patient chart with lab results")
        steps.append("Archive results in document management system")

        if len(abnormal_findings) == 0:
            steps.append("No immediate action required - routine follow-up")

        return steps

    def _calculate_confidence(
        self,
        lab_results: list[LabResult],
        abnormal_findings: list[AbnormalFinding]
    ) -> float:
        """Calculate confidence in processing"""

        confidence = 1.0

        # Reduce confidence for indeterminate results
        indeterminate_count = sum(1 for r in lab_results if r.status == ResultStatus.INDETERMINATE)
        if indeterminate_count > 0:
            confidence -= (indeterminate_count / len(lab_results)) * 0.3

        # Reduce confidence for critical findings (need human verification)
        critical_count = sum(1 for f in abnormal_findings if f.urgency == Urgency.CRITICAL)
        if critical_count > 0:
            confidence -= 0.15

        return max(confidence, 0.5)
