"""
Base Agent Class

Foundation for all AI agents in the platform with:
- Standardized execution interface
- Comprehensive audit logging
- Error handling and retries
- Confidence scoring
- Multi-tenant awareness
"""

import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field
from structlog import get_logger
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_config
from ..shared_services.tenant_context import TenantContext, get_tenant_context
from .audit import AgentAuditLog, AgentAuditService

config = get_config()
logger = get_logger()

# Type variable for agent input
InputType = TypeVar("InputType", bound=BaseModel)
# Type variable for agent output
OutputType = TypeVar("OutputType", bound=BaseModel)


class AgentStatus(str, Enum):
    """Agent execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AgentResult(BaseModel, Generic[OutputType]):
    """
    Standardized agent execution result.

    Contains output, confidence score, and execution metadata.
    """

    # Execution metadata
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    agent_version: str = Field(default="1.0.0")
    status: AgentStatus

    # Output
    output: Optional[OutputType] = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score (0-1)")

    # Error information
    error: Optional[str] = Field(default=None)
    error_details: Optional[dict[str, Any]] = Field(default=None)

    # Execution metrics
    execution_time_ms: float
    retry_count: int = Field(default=0)
    api_calls_made: int = Field(default=0)
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)

    # Audit trail
    started_at: datetime
    completed_at: datetime
    user_id: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)

    # Additional context
    context: dict[str, Any] = Field(default_factory=dict)
    needs_human_review: bool = Field(
        default=False, description="Flag for human review if confidence is low"
    )
    review_reason: Optional[str] = Field(default=None)

    def is_successful(self) -> bool:
        """Check if agent execution was successful."""
        return self.status == AgentStatus.SUCCESS

    def meets_confidence_threshold(self, threshold: float = None) -> bool:
        """
        Check if confidence meets threshold.

        Args:
            threshold: Confidence threshold (uses config default if not provided)

        Returns:
            True if confidence meets threshold
        """
        threshold = threshold or config.agent_confidence_threshold
        return self.confidence >= threshold


class BaseAgent(ABC, Generic[InputType, OutputType]):
    """
    Base class for all AI agents.

    Provides:
    - Standardized execution interface
    - Automatic audit logging
    - Retry logic
    - Multi-tenant awareness
    - Error handling
    """

    def __init__(
        self,
        agent_type: str,
        agent_version: str = "1.0.0",
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ):
        """
        Initialize base agent.

        Args:
            agent_type: Agent type identifier
            agent_version: Agent version
            max_retries: Maximum retry attempts (uses config default if not provided)
            timeout_seconds: Execution timeout (uses config default if not provided)
        """
        self.agent_type = agent_type
        self.agent_version = agent_version
        self.max_retries = max_retries or config.agent_max_retries
        self.timeout_seconds = timeout_seconds or config.agent_timeout_seconds

        self.logger = logger.bind(agent_type=agent_type, agent_version=agent_version)
        self.audit_service = AgentAuditService()

    async def execute(
        self,
        input_data: InputType,
        user_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> AgentResult[OutputType]:
        """
        Execute the agent with full audit logging and error handling.

        Args:
            input_data: Agent input data
            user_id: User initiating the action
            context: Additional context for execution

        Returns:
            Agent execution result
        """
        execution_id = str(uuid4())
        started_at = datetime.utcnow()
        start_time = time.time()

        # Get tenant context
        tenant_context = get_tenant_context()
        tenant_id = tenant_context.tenant_id if tenant_context else None

        self.logger = self.logger.bind(
            execution_id=execution_id, user_id=user_id, tenant_id=tenant_id
        )

        self.logger.info(
            "agent_execution_started",
            input_data=input_data.model_dump() if hasattr(input_data, "model_dump") else str(input_data),
        )

        result: AgentResult[OutputType]

        try:
            # Validate tenant has agent enabled
            if tenant_context and not tenant_context.is_agent_enabled(self.agent_type):
                raise ValueError(f"Agent {self.agent_type} is not enabled for this tenant")

            # Execute with retry logic
            output, confidence, metrics = await self._execute_with_retry(input_data, context or {})

            execution_time_ms = (time.time() - start_time) * 1000
            completed_at = datetime.utcnow()

            # Determine if human review is needed
            needs_review = confidence < config.agent_confidence_threshold
            review_reason = (
                f"Low confidence score: {confidence:.2f} < {config.agent_confidence_threshold}"
                if needs_review
                else None
            )

            result = AgentResult[OutputType](
                execution_id=execution_id,
                agent_type=self.agent_type,
                agent_version=self.agent_version,
                status=AgentStatus.SUCCESS,
                output=output,
                confidence=confidence,
                execution_time_ms=execution_time_ms,
                api_calls_made=metrics.get("api_calls_made", 0),
                tokens_used=metrics.get("tokens_used", 0),
                cost_usd=metrics.get("cost_usd", 0.0),
                started_at=started_at,
                completed_at=completed_at,
                user_id=user_id,
                tenant_id=tenant_id,
                context=context or {},
                needs_human_review=needs_review,
                review_reason=review_reason,
            )

            self.logger.info(
                "agent_execution_success",
                execution_time_ms=execution_time_ms,
                confidence=confidence,
                needs_review=needs_review,
            )

        except RetryError as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Agent failed after {self.max_retries} retries: {str(e)}"

            result = AgentResult[OutputType](
                execution_id=execution_id,
                agent_type=self.agent_type,
                agent_version=self.agent_version,
                status=AgentStatus.FAILED,
                error=error_msg,
                error_details={"retry_count": self.max_retries, "original_error": str(e)},
                execution_time_ms=execution_time_ms,
                retry_count=self.max_retries,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                user_id=user_id,
                tenant_id=tenant_id,
                context=context or {},
                needs_human_review=True,
                review_reason="Agent execution failed after retries",
            )

            self.logger.error("agent_execution_failed", error=error_msg)

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000

            result = AgentResult[OutputType](
                execution_id=execution_id,
                agent_type=self.agent_type,
                agent_version=self.agent_version,
                status=AgentStatus.TIMEOUT,
                error=f"Agent execution exceeded timeout of {self.timeout_seconds}s",
                execution_time_ms=execution_time_ms,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                user_id=user_id,
                tenant_id=tenant_id,
                context=context or {},
                needs_human_review=True,
                review_reason="Agent execution timeout",
            )

            self.logger.error("agent_execution_timeout", timeout_seconds=self.timeout_seconds)

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_trace = traceback.format_exc()

            result = AgentResult[OutputType](
                execution_id=execution_id,
                agent_type=self.agent_type,
                agent_version=self.agent_version,
                status=AgentStatus.FAILED,
                error=str(e),
                error_details={"traceback": error_trace},
                execution_time_ms=execution_time_ms,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                user_id=user_id,
                tenant_id=tenant_id,
                context=context or {},
                needs_human_review=True,
                review_reason=f"Agent execution error: {str(e)}",
            )

            self.logger.error("agent_execution_error", error=str(e), traceback=error_trace)

        # Log to audit trail
        if config.enable_audit_logging and tenant_context:
            try:
                await self._log_to_audit(result, input_data, tenant_context)
            except Exception as e:
                self.logger.error("audit_logging_failed", error=str(e))

        # Increment tenant metrics
        if tenant_context:
            try:
                from ..tenant_management.db_service import TenantDBService

                tenant_service = TenantDBService()
                await tenant_service.increment_agent_actions(tenant_id, 1)
            except Exception as e:
                self.logger.warning("failed_to_increment_tenant_metrics", error=str(e))

        return result

    async def _execute_with_retry(
        self, input_data: InputType, context: dict[str, Any]
    ) -> tuple[OutputType, float, dict[str, Any]]:
        """
        Execute agent with retry logic.

        Args:
            input_data: Agent input
            context: Execution context

        Returns:
            Tuple of (output, confidence, metrics)
        """

        @retry(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        )
        async def _execute():
            return await self._execute_internal(input_data, context)

        return await _execute()

    @abstractmethod
    async def _execute_internal(
        self, input_data: InputType, context: dict[str, Any]
    ) -> tuple[OutputType, float, dict[str, Any]]:
        """
        Internal execution logic implemented by each agent.

        Args:
            input_data: Agent input
            context: Execution context

        Returns:
            Tuple of (output, confidence_score, metrics_dict)
            - output: Agent output data
            - confidence_score: Confidence in result (0.0 to 1.0)
            - metrics_dict: Execution metrics (api_calls_made, tokens_used, cost_usd)
        """
        pass

    async def _log_to_audit(
        self,
        result: AgentResult[OutputType],
        input_data: InputType,
        tenant_context: TenantContext,
    ) -> None:
        """
        Log execution to audit trail.

        Args:
            result: Agent execution result
            input_data: Agent input
            tenant_context: Tenant context
        """
        audit_log = AgentAuditLog(
            log_id=result.execution_id,
            tenant_id=result.tenant_id or "",
            agent_type=self.agent_type,
            agent_version=self.agent_version,
            status=result.status.value,
            input_data=input_data.model_dump() if hasattr(input_data, "model_dump") else {},
            output_data=result.output.model_dump() if result.output and hasattr(result.output, "model_dump") else {},
            confidence=result.confidence,
            execution_time_ms=result.execution_time_ms,
            error=result.error,
            error_details=result.error_details or {},
            retry_count=result.retry_count,
            api_calls_made=result.api_calls_made,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            needs_human_review=result.needs_human_review,
            review_reason=result.review_reason,
            user_id=result.user_id,
            executed_at=result.started_at,
            context=result.context,
        )

        await self.audit_service.create_log(audit_log, tenant_context.db)

    def get_description(self) -> str:
        """
        Get agent description.

        Returns:
            Agent description
        """
        return f"{self.agent_type} v{self.agent_version}"
