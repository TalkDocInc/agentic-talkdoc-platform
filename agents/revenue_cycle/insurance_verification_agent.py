"""
Insurance Verification Agent

Automatically verifies patient insurance eligibility using Stedi EDI integration.

This agent:
1. Takes patient demographics and insurance information
2. Calls Stedi EDI 270 (Eligibility Inquiry) API
3. Parses 271 (Eligibility Response) data
4. Returns verification status with coverage details
5. Flags issues for human review
"""

import httpx
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from platform_core.agent_orchestration.base_agent import BaseAgent
from platform_core.config import get_config
from platform_core.shared_services.tenant_context import get_tenant_context

config = get_config()


class InsuranceVerificationInput(BaseModel):
    """Input for insurance verification agent."""

    # Patient information
    patient_first_name: str
    patient_last_name: str
    patient_date_of_birth: str = Field(..., description="Format: YYYY-MM-DD")
    patient_member_id: str = Field(..., description="Insurance member/subscriber ID")

    # Insurance information
    payer_id: str = Field(..., description="Insurance payer ID")
    payer_name: str = Field(..., description="Insurance company name")

    # Service information (optional)
    service_type_code: str = Field(default="30", description="Service type code (30 = Health Benefit Plan Coverage)")
    service_date: Optional[str] = Field(default=None, description="Date of service (YYYY-MM-DD)")

    # Provider information
    provider_npi: Optional[str] = Field(default=None, description="Provider NPI number")


class CoverageDetails(BaseModel):
    """Coverage details from verification."""

    is_active: bool = Field(description="Is coverage active?")
    plan_name: Optional[str] = Field(default=None)
    coverage_level: Optional[str] = Field(default=None, description="Individual, Family, etc.")
    effective_date: Optional[str] = Field(default=None)
    termination_date: Optional[str] = Field(default=None)

    # Benefit details
    copay_amount: Optional[float] = Field(default=None)
    deductible_amount: Optional[float] = Field(default=None)
    deductible_remaining: Optional[float] = Field(default=None)
    out_of_pocket_max: Optional[float] = Field(default=None)
    out_of_pocket_remaining: Optional[float] = Field(default=None)

    # Service specific
    service_covered: bool = Field(default=True)
    prior_authorization_required: bool = Field(default=False)
    network_status: Optional[str] = Field(default=None, description="In-Network, Out-of-Network")


class InsuranceVerificationOutput(BaseModel):
    """Output from insurance verification agent."""

    verification_status: str = Field(
        description="Status: verified, not_verified, pending, error"
    )
    coverage_details: Optional[CoverageDetails] = Field(default=None)

    # Response metadata
    transaction_id: Optional[str] = Field(default=None)
    response_code: Optional[str] = Field(default=None)
    response_message: Optional[str] = Field(default=None)

    # Flags
    requires_manual_review: bool = Field(default=False)
    issues: list[str] = Field(default_factory=list)

    # Raw response (for audit)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class InsuranceVerificationAgent(BaseAgent[InsuranceVerificationInput, InsuranceVerificationOutput]):
    """
    Agent that verifies insurance eligibility via Stedi EDI.

    Implements the BaseAgent interface with insurance-specific logic.
    """

    def __init__(self):
        """Initialize insurance verification agent."""
        super().__init__(
            agent_type="insurance_verification",
            agent_version="1.0.0",
            max_retries=2,  # Only retry twice for external API calls
            timeout_seconds=30,  # 30 second timeout for API calls
        )

    async def _execute_internal(
        self,
        input_data: InsuranceVerificationInput,
        context: dict[str, Any],
    ) -> tuple[InsuranceVerificationOutput, float, dict[str, Any]]:
        """
        Execute insurance verification.

        Args:
            input_data: Patient and insurance information
            context: Execution context

        Returns:
            Tuple of (output, confidence, metrics)
        """
        # Get tenant context for configuration
        tenant_context = get_tenant_context()

        # Get Stedi credentials from tenant config or platform config
        stedi_api_key = None
        if tenant_context and tenant_context.config.insurance:
            stedi_api_key = tenant_context.config.insurance.clearinghouse_api_key

        if not stedi_api_key:
            stedi_api_key = config.stedi_api_key

        if not stedi_api_key:
            raise ValueError("Stedi API key not configured for tenant or platform")

        # Track metrics
        api_calls_made = 0
        tokens_used = 0
        cost_usd = 0.0

        try:
            # Step 1: Build EDI 270 (Eligibility Inquiry) request
            edi_request = self._build_270_request(input_data, tenant_context)

            # Step 2: Call Stedi API
            verification_response = await self._call_stedi_api(edi_request, stedi_api_key)
            api_calls_made += 1
            cost_usd += 0.10  # Approximate cost per verification

            # Step 3: Parse EDI 271 (Eligibility Response)
            output = self._parse_271_response(verification_response)

            # Step 4: Determine confidence based on response
            confidence = self._calculate_confidence(output, verification_response)

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }

            return output, confidence, metrics

        except httpx.HTTPStatusError as e:
            # API error - return error output with low confidence
            self.logger.error("stedi_api_error", status_code=e.response.status_code, error=str(e))

            output = InsuranceVerificationOutput(
                verification_status="error",
                response_message=f"API Error: {e.response.status_code}",
                requires_manual_review=True,
                issues=[f"Stedi API returned {e.response.status_code}"],
            )

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": 0,
                "cost_usd": cost_usd,
            }

            return output, 0.0, metrics

        except Exception as e:
            # Unexpected error
            self.logger.error("verification_error", error=str(e))

            output = InsuranceVerificationOutput(
                verification_status="error",
                response_message=f"Verification failed: {str(e)}",
                requires_manual_review=True,
                issues=[str(e)],
            )

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": 0,
                "cost_usd": cost_usd,
            }

            return output, 0.0, metrics

    def _build_270_request(
        self,
        input_data: InsuranceVerificationInput,
        tenant_context,
    ) -> dict[str, Any]:
        """
        Build EDI 270 eligibility inquiry request.

        Args:
            input_data: Patient and insurance information
            tenant_context: Tenant context for provider info

        Returns:
            EDI 270 request payload
        """
        # Get provider information from tenant config
        provider_npi = input_data.provider_npi
        organization_name = "TalkDoc"  # Default
        organization_npi = config.stedi_account_id

        if tenant_context and tenant_context.config.insurance:
            organization_name = tenant_context.config.insurance.organization_name
            organization_npi = tenant_context.config.insurance.organization_npi

        # Build 270 request (simplified - actual Stedi format would be more complex)
        request = {
            "transaction_type": "270",
            "information_source": {
                "payer_id": input_data.payer_id,
                "payer_name": input_data.payer_name,
            },
            "information_receiver": {
                "organization_name": organization_name,
                "npi": organization_npi,
            },
            "subscriber": {
                "member_id": input_data.patient_member_id,
                "first_name": input_data.patient_first_name,
                "last_name": input_data.patient_last_name,
                "date_of_birth": input_data.patient_date_of_birth,
            },
            "service_type_code": input_data.service_type_code,
            "service_date": input_data.service_date or datetime.utcnow().strftime("%Y-%m-%d"),
        }

        return request

    async def _call_stedi_api(
        self,
        edi_request: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any]:
        """
        Call Stedi EDI API.

        Args:
            edi_request: EDI 270 request
            api_key: Stedi API key

        Returns:
            EDI 271 response
        """
        # Note: This is a simplified example
        # Real implementation would use Stedi's actual API format

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://edi.us.stedi.com/2024-01-01/x12/eligibility-inquiry",
                json=edi_request,
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

            response.raise_for_status()
            return response.json()

    def _parse_271_response(self, response: dict[str, Any]) -> InsuranceVerificationOutput:
        """
        Parse EDI 271 eligibility response.

        Args:
            response: EDI 271 response from Stedi

        Returns:
            Structured verification output
        """
        # Simplified parsing - real implementation would parse full EDI 271 structure
        # For this POC, we'll create a mock successful response

        is_active = response.get("eligibility", {}).get("active", False)
        status = "verified" if is_active else "not_verified"

        coverage_details = None
        if is_active:
            coverage_details = CoverageDetails(
                is_active=True,
                plan_name=response.get("plan_name", "Unknown Plan"),
                coverage_level=response.get("coverage_level", "Individual"),
                effective_date=response.get("effective_date"),
                termination_date=response.get("termination_date"),
                copay_amount=response.get("copay"),
                deductible_amount=response.get("deductible"),
                deductible_remaining=response.get("deductible_remaining"),
                out_of_pocket_max=response.get("oop_max"),
                out_of_pocket_remaining=response.get("oop_remaining"),
                service_covered=response.get("service_covered", True),
                prior_authorization_required=response.get("prior_auth_required", False),
                network_status=response.get("network_status", "In-Network"),
            )

        output = InsuranceVerificationOutput(
            verification_status=status,
            coverage_details=coverage_details,
            transaction_id=response.get("transaction_id"),
            response_code=response.get("response_code"),
            response_message=response.get("message", "Verification complete"),
            requires_manual_review=not is_active,
            issues=response.get("issues", []),
            raw_response=response,
        )

        return output

    def _calculate_confidence(
        self,
        output: InsuranceVerificationOutput,
        raw_response: dict[str, Any],
    ) -> float:
        """
        Calculate confidence score for verification.

        Args:
            output: Parsed output
            raw_response: Raw API response

        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = 0.5  # Base confidence

        # Increase confidence if verified
        if output.verification_status == "verified":
            confidence += 0.3

        # Increase if we have detailed coverage information
        if output.coverage_details:
            confidence += 0.1
            if output.coverage_details.copay_amount is not None:
                confidence += 0.05
            if output.coverage_details.deductible_amount is not None:
                confidence += 0.05

        # Decrease if there are issues
        if output.issues:
            confidence -= 0.1 * len(output.issues)

        # Decrease if response code indicates issues
        if output.response_code and output.response_code != "AA":  # AA = Approved
            confidence -= 0.2

        # Ensure confidence stays in valid range
        return max(0.0, min(1.0, confidence))
