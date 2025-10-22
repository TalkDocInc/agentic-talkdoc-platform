"""
Agent Execution API Router

REST API endpoints for executing agents and managing agent tasks.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from structlog import get_logger

from agents.care_coordination import (
    PatientIntakeAgent,
    PatientIntakeInput,
    SmartSchedulingAgent,
    SmartSchedulingInput,
)
from agents.revenue_cycle import (
    ClaimsGenerationAgent,
    ClaimsGenerationInput,
    InsuranceVerificationAgent,
    InsuranceVerificationInput,
    MedicalCodingAgent,
    MedicalCodingInput,
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
