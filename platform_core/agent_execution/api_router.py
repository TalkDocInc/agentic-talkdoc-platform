"""
Agent Execution API Router

REST API endpoints for executing agents and managing agent tasks.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from structlog import get_logger

from agents.care_coordination import (
    AppointmentRemindersAgent,
    AppointmentRemindersInput,
    CarePlanManagementAgent,
    CarePlanManagementInput,
    ClinicalDocumentationAgent,
    ClinicalDocumentationInput,
    LabResultsProcessingAgent,
    LabResultsProcessingInput,
    PatientIntakeAgent,
    PatientIntakeInput,
    ReferralManagementAgent,
    ReferralManagementInput,
    SmartSchedulingAgent,
    SmartSchedulingInput,
)
from agents.patient_engagement import (
    AIHealthAdvisorAgent,
    AIHealthAdvisorInput,
    PrescriptionManagementAgent,
    PrescriptionManagementInput,
    TriageAgent,
    TriageInput,
)
from agents.revenue_cycle import (
    ClaimsGenerationAgent,
    ClaimsGenerationInput,
    ClaimsStatusTrackingAgent,
    ClaimsStatusTrackingInput,
    DenialManagementAgent,
    DenialManagementInput,
    InsuranceVerificationAgent,
    InsuranceVerificationInput,
    MedicalCodingAgent,
    MedicalCodingInput,
    PaymentPostingAgent,
    PaymentPostingInput,
)
from ..agent_orchestration.audit import AgentAuditService
from ..auth.dependencies import get_current_user, require_role
from ..auth.models import User, UserRole
from ..shared_services.tenant_context import get_tenant_context

logger = get_logger()

router = APIRouter(prefix="/agents", tags=["Agent Execution"])


# Generic agent execution request/response models


class AgentExecutionRequest(BaseModel):
    """Generic agent execution request."""

    agent_type: str = Field(..., description="Type of agent to execute")
    input_data: dict[str, Any] = Field(..., description="Agent input data")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context")


class AgentExecutionResponse(BaseModel):
    """Agent execution response."""

    execution_id: str
    agent_type: str
    agent_version: str
    status: str
    output: Optional[dict[str, Any]] = None
    confidence: float
    execution_time_ms: float
    needs_human_review: bool
    review_reason: Optional[str] = None
    error: Optional[str] = None


# Revenue Cycle Agent Endpoints


@router.post(
    "/insurance-verification",
    response_model=AgentExecutionResponse,
    summary="Verify Insurance Eligibility",
    description="Execute insurance verification agent to check patient eligibility",
)
async def verify_insurance(
    request: InsuranceVerificationInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute insurance verification agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled for this tenant
    if not tenant_context.is_agent_enabled("insurance_verification"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insurance verification agent is not enabled for this tenant",
        )

    logger.info(
        "executing_insurance_verification_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
    )

    # Execute agent
    agent = InsuranceVerificationAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    # Convert result to response
    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/medical-coding",
    response_model=AgentExecutionResponse,
    summary="Extract Medical Codes",
    description="Execute medical coding agent to extract CPT and ICD codes from clinical notes",
)
async def extract_medical_codes(
    request: MedicalCodingInput,
    llm_provider: str = Query("anthropic", description="LLM provider (openai or anthropic)"),
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute medical coding agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("medical_coding"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Medical coding agent is not enabled for this tenant",
        )

    logger.info(
        "executing_medical_coding_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        llm_provider=llm_provider,
    )

    # Execute agent
    agent = MedicalCodingAgent(llm_provider=llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/claims-generation",
    response_model=AgentExecutionResponse,
    summary="Generate and Submit Insurance Claim",
    description="Execute claims generation agent to create and submit EDI 837 claims to insurance payers",
)
async def generate_claim(
    request: ClaimsGenerationInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute claims generation agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("claims_generation"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Claims generation agent is not enabled for this tenant",
        )

    logger.info(
        "executing_claims_generation_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        claim_type=request.claim_type,
    )

    # Execute agent
    agent = ClaimsGenerationAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/claims-status-tracking",
    response_model=AgentExecutionResponse,
    summary="Track Claims Status",
    description="Execute claims status tracking agent to monitor submitted claims and detect issues",
)
async def track_claims_status(
    request: ClaimsStatusTrackingInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute claims status tracking agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("claims_status_tracking"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Claims status tracking agent is not enabled for this tenant",
        )

    logger.info(
        "executing_claims_status_tracking_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        claims_count=len(request.claims_to_check),
    )

    # Execute agent
    agent = ClaimsStatusTrackingAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/denial-management",
    response_model=AgentExecutionResponse,
    summary="Analyze Claim Denial and Generate Appeal",
    description="Execute denial management agent to analyze denials and automate appeals process",
)
async def analyze_denial(
    request: DenialManagementInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute denial management agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("denial_management"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Denial management agent is not enabled for this tenant",
        )

    logger.info(
        "executing_denial_management_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        claim_id=request.denial.claim_id,
        denied_amount=request.denial.denied_amount,
    )

    # Execute agent
    agent = DenialManagementAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/payment-posting",
    response_model=AgentExecutionResponse,
    summary="Process ERA and Post Payments",
    description="Execute payment posting agent to process ERA and reconcile payments with automatic variance detection",
)
async def post_payment(
    request: PaymentPostingInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute payment posting agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("payment_posting"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payment posting agent is not enabled for this tenant",
        )

    logger.info(
        "executing_payment_posting_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        era_id=request.era_data.era_id,
        payment_amount=request.era_data.total_payment_amount,
        action=request.action,
    )

    # Execute agent
    agent = PaymentPostingAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


# Care Coordination Agent Endpoints


@router.post(
    "/patient-intake",
    response_model=AgentExecutionResponse,
    summary="Process Patient Intake",
    description="Execute patient intake agent to validate and process patient onboarding",
)
async def process_patient_intake(
    request: PatientIntakeInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute patient intake agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("patient_intake"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient intake agent is not enabled for this tenant",
        )

    logger.info(
        "executing_patient_intake_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
    )

    # Execute agent
    agent = PatientIntakeAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/smart-scheduling",
    response_model=AgentExecutionResponse,
    summary="Match Patient with Clinicians",
    description="Execute smart scheduling agent to match patients with optimal clinicians based on multiple factors",
)
async def match_patient_to_clinician(
    request: SmartSchedulingInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute smart scheduling agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("smart_scheduling"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Smart scheduling agent is not enabled for this tenant",
        )

    logger.info(
        "executing_smart_scheduling_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_id,
        specialty=request.specialty_required,
    )

    # Execute agent
    agent = SmartSchedulingAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/appointment-reminders",
    response_model=AgentExecutionResponse,
    summary="Schedule Appointment Reminders",
    description="Execute appointment reminders agent to schedule automated notifications across multiple channels",
)
async def schedule_appointment_reminders(
    request: AppointmentRemindersInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute appointment reminders agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("appointment_reminders"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Appointment reminders agent is not enabled for this tenant",
        )

    logger.info(
        "executing_appointment_reminders_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        appointment_id=request.appointment.appointment_id,
        patient_id=request.patient_contact.patient_id,
    )

    # Execute agent
    agent = AppointmentRemindersAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/care-plan-management",
    response_model=AgentExecutionResponse,
    summary="Create or Manage Care Plan",
    description="Execute care plan management agent to create, update, or evaluate patient care plans",
)
async def manage_care_plan(
    request: CarePlanManagementInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute care plan management agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("care_plan_management"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Care plan management agent is not enabled for this tenant",
        )

    logger.info(
        "executing_care_plan_management_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_profile.patient_id,
        action=request.action,
    )

    # Execute agent
    agent = CarePlanManagementAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/clinical-documentation",
    response_model=AgentExecutionResponse,
    summary="Generate Clinical Documentation",
    description="Execute clinical documentation agent to generate AI-assisted progress notes and encounter summaries",
)
async def generate_clinical_documentation(
    request: ClinicalDocumentationInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute clinical documentation agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("clinical_documentation"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinical documentation agent is not enabled for this tenant",
        )

    logger.info(
        "executing_clinical_documentation_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.encounter.patient_id,
        documentation_type=request.documentation_type,
    )

    # Execute agent
    agent = ClinicalDocumentationAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/referral-management",
    response_model=AgentExecutionResponse,
    summary="Manage Specialist Referrals",
    description="Execute referral management agent to coordinate specialist referrals, track status, and ensure clinical handoffs",
)
async def manage_referral(
    request: ReferralManagementInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute referral management agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("referral_management"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral management agent is not enabled for this tenant",
        )

    logger.info(
        "executing_referral_management_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_id,
        specialty_needed=request.specialty_needed,
        action=request.action,
    )

    # Execute agent
    agent = ReferralManagementAgent(llm_provider="anthropic")
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/lab-results-processing",
    response_model=AgentExecutionResponse,
    summary="Process Lab Results",
    description="Execute lab results processing agent to interpret results, flag abnormal values, and notify patients",
)
async def process_lab_results(
    request: LabResultsProcessingInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute lab results processing agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("lab_results_processing"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lab results processing agent is not enabled for this tenant",
        )

    logger.info(
        "executing_lab_results_processing_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        order_id=request.order_id,
        test_count=len(request.lab_tests),
    )

    # Execute agent
    agent = LabResultsProcessingAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


# Patient Engagement Agent Endpoints


@router.post(
    "/ai-health-advisor",
    response_model=AgentExecutionResponse,
    summary="AI Health Advisor Chat",
    description="Execute AI health advisor agent for conversational health guidance with safety checks",
)
async def chat_with_ai_advisor(
    request: AIHealthAdvisorInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute AI health advisor agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("ai_health_advisor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI health advisor agent is not enabled for this tenant",
        )

    logger.info(
        "executing_ai_health_advisor_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_context.patient_id,
        specialty=request.specialty_context,
    )

    # Execute agent
    agent = AIHealthAdvisorAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/prescription-management",
    response_model=AgentExecutionResponse,
    summary="Manage Prescriptions and Refills",
    description="Execute prescription management agent for refills, adherence monitoring, and issue detection",
)
async def manage_prescriptions(
    request: PrescriptionManagementInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute prescription management agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("prescription_management"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prescription management agent is not enabled for this tenant",
        )

    logger.info(
        "executing_prescription_management_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_profile.patient_id,
        action=request.action,
    )

    # Execute agent
    agent = PrescriptionManagementAgent()
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


@router.post(
    "/triage",
    response_model=AgentExecutionResponse,
    summary="Triage Patient Symptoms",
    description="Execute triage agent to assess symptoms, determine urgency, and route to appropriate care",
)
async def triage_patient(
    request: TriageInput,
    current_user: User = Depends(get_current_user),
) -> AgentExecutionResponse:
    """Execute triage agent."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Check if agent is enabled
    if not tenant_context.is_agent_enabled("triage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Triage agent is not enabled for this tenant",
        )

    logger.info(
        "executing_triage_agent",
        user_id=current_user.user_id,
        tenant_id=tenant_context.tenant_id,
        patient_id=request.patient_context.patient_id,
        chief_complaint=request.chief_complaint,
    )

    # Execute agent
    agent = TriageAgent(llm_provider=request.llm_provider)
    result = await agent.execute(
        input_data=request,
        user_id=current_user.user_id,
        context={"llm_provider": request.llm_provider},
    )

    return AgentExecutionResponse(
        execution_id=result.execution_id,
        agent_type=result.agent_type,
        agent_version=result.agent_version,
        status=result.status.value,
        output=result.output.model_dump() if result.output else None,
        confidence=result.confidence,
        execution_time_ms=result.execution_time_ms,
        needs_human_review=result.needs_human_review,
        review_reason=result.review_reason,
        error=result.error,
    )


# Agent Audit and History Endpoints


@router.get(
    "/executions",
    summary="List Agent Executions",
    description="List all agent executions with filtering (requires authentication)",
)
async def list_agent_executions(
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    needs_review: Optional[bool] = Query(None, description="Filter by review flag"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> dict:
    """List agent execution history."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    audit_service = AgentAuditService()

    # Get audit logs
    logs = await audit_service.list_logs(
        db=tenant_context.db,
        agent_type=agent_type,
        user_id=None,  # Can see all users' executions (or filter by current_user.user_id for user-only)
        status=status,
        needs_review=needs_review,
        skip=skip,
        limit=limit,
    )

    # Count total
    total = await audit_service.count_logs(
        db=tenant_context.db,
        agent_type=agent_type,
        status=status,
        needs_review=needs_review,
    )

    return {
        "executions": [log.model_dump() for log in logs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/executions/{execution_id}",
    summary="Get Agent Execution Details",
    description="Get detailed information about a specific agent execution",
)
async def get_agent_execution(
    execution_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get specific agent execution details."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    audit_service = AgentAuditService()

    log = await audit_service.get_log(execution_id, tenant_context.db)

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    return log.model_dump()


@router.post(
    "/executions/{execution_id}/review",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.MANAGER))],
    summary="Mark Execution as Reviewed",
    description="Mark an agent execution as reviewed (requires manager role)",
)
async def mark_execution_reviewed(
    execution_id: str,
    review_notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
) -> None:
    """Mark agent execution as reviewed."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    audit_service = AgentAuditService()

    success = await audit_service.mark_reviewed(
        log_id=execution_id,
        reviewed_by=current_user.user_id,
        review_notes=review_notes,
        db=tenant_context.db,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    logger.info(
        "execution_marked_reviewed",
        execution_id=execution_id,
        reviewed_by=current_user.user_id,
    )


@router.get(
    "/statistics",
    summary="Get Agent Statistics",
    description="Get aggregate statistics about agent executions",
)
async def get_agent_statistics(
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get agent execution statistics."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    audit_service = AgentAuditService()

    stats = await audit_service.get_agent_stats(
        db=tenant_context.db,
        agent_type=agent_type,
    )

    return stats
