"""
Claims Generation Agent

Automatically generates and submits insurance claims to Stedi EDI.
Integrates with Medical Coding Agent output to create EDI 837 claims.
"""

import json
from datetime import datetime
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


class ProviderInfo(BaseModel):
    """Provider/Clinician information."""

    npi: str = Field(..., description="National Provider Identifier")
    tax_id: str = Field(..., description="Tax ID (EIN or SSN)")
    first_name: str
    last_name: str
    organization_name: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    phone: str
    specialty_code: str = Field(..., description="Taxonomy code for specialty")


class PatientInfo(BaseModel):
    """Patient demographic information."""

    member_id: str = Field(..., description="Insurance member ID")
    first_name: str
    last_name: str
    date_of_birth: str = Field(..., description="YYYY-MM-DD format")
    gender: str = Field(..., description="M, F, or U")
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    phone: Optional[str] = None
    relationship_to_subscriber: str = Field(default="self", description="self, spouse, child, etc.")


class SubscriberInfo(BaseModel):
    """Insurance subscriber information (if different from patient)."""

    member_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    gender: str
    relationship_to_patient: str = Field(..., description="self, spouse, parent, etc.")


class InsurancePayerInfo(BaseModel):
    """Insurance payer information."""

    payer_id: str = Field(..., description="Stedi payer ID or Payer ID from 270/271")
    payer_name: str
    payer_type: str = Field(default="primary", description="primary, secondary, tertiary")


class ServiceLine(BaseModel):
    """Individual service line on claim."""

    service_date: str = Field(..., description="YYYY-MM-DD format")
    cpt_code: str = Field(..., description="CPT/HCPCS procedure code")
    modifiers: list[str] = Field(default_factory=list, description="CPT modifiers")
    units: int = Field(default=1, description="Number of units")
    charge_amount: float = Field(..., description="Charge amount in dollars")
    diagnosis_pointers: list[int] = Field(..., description="References to diagnosis codes (1-indexed)")
    place_of_service: str = Field(default="11", description="Place of service code")
    rendering_provider_npi: Optional[str] = None


class ClaimsGenerationInput(BaseModel):
    """Input for claims generation agent."""

    claim_type: str = Field(default="professional", description="professional, institutional, or dental")
    patient: PatientInfo
    subscriber: Optional[SubscriberInfo] = Field(None, description="If different from patient")
    insurance_payer: InsurancePayerInfo
    rendering_provider: ProviderInfo
    billing_provider: Optional[ProviderInfo] = Field(None, description="If different from rendering")
    diagnosis_codes: list[str] = Field(..., description="ICD-10 diagnosis codes (from Medical Coding Agent)")
    service_lines: list[ServiceLine] = Field(..., description="Service lines with CPT codes")
    claim_note: Optional[str] = Field(None, description="Additional claim notes")
    prior_authorization_number: Optional[str] = None
    referral_number: Optional[str] = None


class ClaimSubmissionResult(BaseModel):
    """Result of claim submission."""

    claim_id: str = Field(..., description="Generated claim ID")
    submission_id: str = Field(..., description="Stedi submission/transaction ID")
    status: str = Field(..., description="submitted, accepted, rejected, pending")
    payer_claim_control_number: Optional[str] = Field(None, description="Payer's claim number (if available)")
    submission_timestamp: str
    total_charge_amount: float


class ClaimsGenerationOutput(BaseModel):
    """Output from claims generation agent."""

    result: ClaimSubmissionResult
    validation_warnings: list[str] = Field(default_factory=list, description="Non-fatal validation warnings")
    edi_transaction_set_id: str = Field(..., description="EDI 837 transaction set control number")


# Agent Implementation


class ClaimsGenerationAgent(BaseAgent[ClaimsGenerationInput, ClaimsGenerationOutput]):
    """
    Claims Generation Agent.

    Automatically generates EDI 837 claims and submits them to insurance payers via Stedi EDI.
    Integrates with Medical Coding Agent output to create compliant claims.
    """

    def __init__(self):
        super().__init__(
            agent_type="claims_generation",
            agent_version="1.0.0",
            description="Auto-generate and submit insurance claims to payers",
        )

    async def _execute_internal(
        self,
        input_data: ClaimsGenerationInput,
        context: dict[str, Any],
    ) -> tuple[ClaimsGenerationOutput, float, dict[str, Any]]:
        """Execute claims generation logic."""
        start_time = datetime.now()

        # Step 1: Validate claim data
        validation_warnings = self._validate_claim_data(input_data)

        # Step 2: Build EDI 837 transaction
        edi_payload = self._build_edi_837(input_data)

        # Step 3: Submit to Stedi
        submission_result = await self._submit_to_stedi(edi_payload, input_data)

        # Step 4: Calculate confidence
        confidence = self._calculate_claim_confidence(input_data, validation_warnings, submission_result)

        # Step 5: Create output
        output = ClaimsGenerationOutput(
            result=submission_result,
            validation_warnings=validation_warnings,
            edi_transaction_set_id=edi_payload["transaction_set_control_number"],
        )

        execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        metadata = {
            "claim_type": input_data.claim_type,
            "payer_id": input_data.insurance_payer.payer_id,
            "service_line_count": len(input_data.service_lines),
            "total_charge": sum(line.charge_amount for line in input_data.service_lines),
            "validation_warning_count": len(validation_warnings),
            "execution_time_ms": execution_time_ms,
        }

        return output, confidence, metadata

    def _validate_claim_data(self, input_data: ClaimsGenerationInput) -> list[str]:
        """Validate claim data and return warnings."""
        warnings = []

        # Validate diagnosis codes
        if not input_data.diagnosis_codes:
            warnings.append("No diagnosis codes provided")
        elif len(input_data.diagnosis_codes) > 12:
            warnings.append(f"Too many diagnosis codes ({len(input_data.diagnosis_codes)}), maximum is 12")

        # Validate service lines
        if not input_data.service_lines:
            warnings.append("No service lines provided")

        for idx, line in enumerate(input_data.service_lines):
            # Validate diagnosis pointers
            for pointer in line.diagnosis_pointers:
                if pointer < 1 or pointer > len(input_data.diagnosis_codes):
                    warnings.append(
                        f"Service line {idx + 1}: Invalid diagnosis pointer {pointer} "
                        f"(only {len(input_data.diagnosis_codes)} diagnoses provided)"
                    )

            # Validate charge amount
            if line.charge_amount <= 0:
                warnings.append(f"Service line {idx + 1}: Invalid charge amount ${line.charge_amount}")

            # Validate CPT code format (basic check)
            if not line.cpt_code or len(line.cpt_code) != 5:
                warnings.append(f"Service line {idx + 1}: Invalid CPT code format '{line.cpt_code}'")

            # Validate units
            if line.units < 1:
                warnings.append(f"Service line {idx + 1}: Invalid units {line.units}")

        # Validate NPIs (basic format check)
        if len(input_data.rendering_provider.npi) != 10:
            warnings.append(f"Invalid rendering provider NPI format: {input_data.rendering_provider.npi}")

        # Validate patient demographics
        try:
            dob = datetime.strptime(input_data.patient.date_of_birth, "%Y-%m-%d")
            if dob > datetime.now():
                warnings.append("Patient date of birth is in the future")
        except ValueError:
            warnings.append(f"Invalid patient date of birth format: {input_data.patient.date_of_birth}")

        # Validate service dates
        for idx, line in enumerate(input_data.service_lines):
            try:
                service_date = datetime.strptime(line.service_date, "%Y-%m-%d")
                if service_date > datetime.now():
                    warnings.append(f"Service line {idx + 1}: Service date is in the future")
            except ValueError:
                warnings.append(f"Service line {idx + 1}: Invalid service date format '{line.service_date}'")

        # Validate subscriber (if different from patient)
        if input_data.subscriber and input_data.subscriber.relationship_to_patient == "self":
            warnings.append("Subscriber relationship should not be 'self' if subscriber is different from patient")

        return warnings

    def _build_edi_837(self, input_data: ClaimsGenerationInput) -> dict[str, Any]:
        """
        Build EDI 837 transaction payload for Stedi API.

        Returns a dictionary representing the EDI 837 transaction.
        """
        # Generate unique identifiers
        transaction_control_number = str(uuid4())[:9]  # 9-digit control number
        claim_id = f"CLM-{uuid4()}"

        # Determine subscriber (patient or separate subscriber)
        subscriber = input_data.subscriber if input_data.subscriber else None
        is_subscriber_patient = subscriber is None

        # Build billing provider (use rendering if not specified)
        billing_provider = input_data.billing_provider if input_data.billing_provider else input_data.rendering_provider

        # Calculate total charge
        total_charge = sum(line.charge_amount for line in input_data.service_lines)

        # Build EDI 837 payload structure for Stedi
        # This is a simplified representation - actual Stedi API may require different structure
        payload = {
            "transaction_set_control_number": transaction_control_number,
            "claim_id": claim_id,
            "claim_type": input_data.claim_type,
            "total_charge_amount": total_charge,
            # Billing Provider (Loop 2010AA)
            "billing_provider": {
                "npi": billing_provider.npi,
                "tax_id": billing_provider.tax_id,
                "organization_name": billing_provider.organization_name,
                "first_name": billing_provider.first_name,
                "last_name": billing_provider.last_name,
                "address": {
                    "address_line1": billing_provider.address_line1,
                    "address_line2": billing_provider.address_line2,
                    "city": billing_provider.city,
                    "state": billing_provider.state,
                    "zip_code": billing_provider.zip_code,
                },
                "phone": billing_provider.phone,
            },
            # Subscriber (Loop 2010BA)
            "subscriber": {
                "member_id": subscriber.member_id if subscriber else input_data.patient.member_id,
                "first_name": subscriber.first_name if subscriber else input_data.patient.first_name,
                "last_name": subscriber.last_name if subscriber else input_data.patient.last_name,
                "date_of_birth": subscriber.date_of_birth if subscriber else input_data.patient.date_of_birth,
                "gender": subscriber.gender if subscriber else input_data.patient.gender,
            },
            # Patient (Loop 2010CA) - if different from subscriber
            "patient": None
            if is_subscriber_patient
            else {
                "first_name": input_data.patient.first_name,
                "last_name": input_data.patient.last_name,
                "date_of_birth": input_data.patient.date_of_birth,
                "gender": input_data.patient.gender,
                "address": {
                    "address_line1": input_data.patient.address_line1,
                    "address_line2": input_data.patient.address_line2,
                    "city": input_data.patient.city,
                    "state": input_data.patient.state,
                    "zip_code": input_data.patient.zip_code,
                },
                "relationship_to_subscriber": input_data.patient.relationship_to_subscriber,
            },
            # Payer (Loop 2010BB)
            "payer": {
                "payer_id": input_data.insurance_payer.payer_id,
                "payer_name": input_data.insurance_payer.payer_name,
            },
            # Rendering Provider (Loop 2310B)
            "rendering_provider": {
                "npi": input_data.rendering_provider.npi,
                "first_name": input_data.rendering_provider.first_name,
                "last_name": input_data.rendering_provider.last_name,
                "taxonomy_code": input_data.rendering_provider.specialty_code,
            },
            # Claim information (Segment CLM)
            "claim_information": {
                "claim_filing_indicator": "CI" if input_data.insurance_payer.payer_type == "primary" else "MB",
                "prior_authorization_number": input_data.prior_authorization_number,
                "referral_number": input_data.referral_number,
            },
            # Diagnosis codes (Segment HI)
            "diagnosis_codes": [
                {"code": code, "code_type": "ABK"}  # ABK = ICD-10
                for code in input_data.diagnosis_codes[:12]  # Max 12 diagnoses
            ],
            # Service lines (Loop 2400)
            "service_lines": [
                {
                    "line_number": idx + 1,
                    "service_date": line.service_date,
                    "place_of_service": line.place_of_service,
                    "procedure_code": line.cpt_code,
                    "modifiers": line.modifiers,
                    "charge_amount": line.charge_amount,
                    "units": line.units,
                    "diagnosis_pointers": line.diagnosis_pointers,
                    "rendering_provider_npi": line.rendering_provider_npi or input_data.rendering_provider.npi,
                }
                for idx, line in enumerate(input_data.service_lines)
            ],
            # Additional claim notes
            "claim_note": input_data.claim_note,
        }

        return payload

    async def _submit_to_stedi(
        self, edi_payload: dict[str, Any], input_data: ClaimsGenerationInput
    ) -> ClaimSubmissionResult:
        """Submit EDI 837 claim to Stedi API."""
        if not config.stedi_api_key:
            logger.warning("stedi_api_key_not_configured", message="Using mock submission")
            return self._mock_claim_submission(edi_payload, input_data)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Stedi Claims API endpoint for EDI 837 submission
                # Actual endpoint may vary - this is illustrative
                url = f"{config.stedi_api_url}/claims/submit"

                headers = {
                    "Authorization": f"Bearer {config.stedi_api_key}",
                    "Content-Type": "application/json",
                }

                # Prepare request body
                request_body = {
                    "transactionType": "837",  # Professional claim
                    "payload": edi_payload,
                }

                logger.info(
                    "submitting_claim_to_stedi",
                    claim_id=edi_payload["claim_id"],
                    payer_id=input_data.insurance_payer.payer_id,
                )

                response = await client.post(url, headers=headers, json=request_body)
                response.raise_for_status()

                result = response.json()

                # Parse Stedi response
                submission_result = ClaimSubmissionResult(
                    claim_id=edi_payload["claim_id"],
                    submission_id=result.get("submissionId", result.get("transactionId", str(uuid4()))),
                    status=self._map_stedi_status(result.get("status", "submitted")),
                    payer_claim_control_number=result.get("payerClaimControlNumber"),
                    submission_timestamp=datetime.now().isoformat(),
                    total_charge_amount=edi_payload["total_charge_amount"],
                )

                logger.info(
                    "claim_submitted_successfully",
                    claim_id=submission_result.claim_id,
                    submission_id=submission_result.submission_id,
                    status=submission_result.status,
                )

                return submission_result

        except httpx.HTTPStatusError as e:
            logger.error(
                "stedi_api_error",
                status_code=e.response.status_code,
                response=e.response.text,
                error=str(e),
            )
            raise ValueError(f"Stedi API error: {e.response.status_code} - {e.response.text}")

        except Exception as e:
            logger.error("claim_submission_error", error=str(e))
            raise ValueError(f"Failed to submit claim: {str(e)}")

    def _mock_claim_submission(
        self, edi_payload: dict[str, Any], input_data: ClaimsGenerationInput
    ) -> ClaimSubmissionResult:
        """Mock claim submission for testing when Stedi API is not configured."""
        logger.info("using_mock_claim_submission", claim_id=edi_payload["claim_id"])

        return ClaimSubmissionResult(
            claim_id=edi_payload["claim_id"],
            submission_id=f"MOCK-{uuid4()}",
            status="submitted",
            payer_claim_control_number=f"PCN-{uuid4()}"[:15],
            submission_timestamp=datetime.now().isoformat(),
            total_charge_amount=edi_payload["total_charge_amount"],
        )

    def _map_stedi_status(self, stedi_status: str) -> str:
        """Map Stedi API status to standardized status."""
        status_mapping = {
            "submitted": "submitted",
            "accepted": "accepted",
            "rejected": "rejected",
            "pending": "pending",
            "acknowledged": "accepted",
            "failed": "rejected",
        }
        return status_mapping.get(stedi_status.lower(), "submitted")

    def _calculate_claim_confidence(
        self,
        input_data: ClaimsGenerationInput,
        validation_warnings: list[str],
        submission_result: ClaimSubmissionResult,
    ) -> float:
        """Calculate confidence score for claim submission."""
        confidence = 1.0

        # Reduce confidence for validation warnings
        if validation_warnings:
            confidence -= len(validation_warnings) * 0.05  # -5% per warning
            confidence = max(confidence, 0.6)  # Minimum 60% if there are warnings

        # Reduce confidence if submission was rejected
        if submission_result.status == "rejected":
            confidence = min(confidence, 0.5)  # Max 50% for rejected claims

        # Reduce confidence if no payer claim control number
        if not submission_result.payer_claim_control_number:
            confidence -= 0.1

        # Increase confidence if accepted
        if submission_result.status == "accepted":
            confidence = min(confidence + 0.1, 1.0)

        # Reduce confidence for claims with many service lines (higher complexity)
        if len(input_data.service_lines) > 20:
            confidence -= 0.1

        # Reduce confidence if missing prior auth (when it might be needed)
        # This is a simple heuristic - actual rules would be more complex
        high_cost_services = [line for line in input_data.service_lines if line.charge_amount > 1000]
        if high_cost_services and not input_data.prior_authorization_number:
            confidence -= 0.15

        return max(0.0, min(1.0, confidence))

    def _determine_review_needed(
        self,
        output: ClaimsGenerationOutput,
        confidence: float,
        input_data: ClaimsGenerationInput,
    ) -> tuple[bool, Optional[str]]:
        """Determine if human review is needed."""
        # Review if confidence is low
        if confidence < 0.75:
            return True, f"Low confidence ({confidence:.2f})"

        # Review if submission was rejected
        if output.result.status == "rejected":
            return True, "Claim was rejected by payer"

        # Review if there are validation warnings
        if len(output.validation_warnings) >= 3:
            return True, f"{len(output.validation_warnings)} validation warnings"

        # Review for high-value claims
        if output.result.total_charge_amount > 5000:
            return True, f"High-value claim (${output.result.total_charge_amount:,.2f})"

        # Review if many service lines
        if len(input_data.service_lines) > 15:
            return True, f"{len(input_data.service_lines)} service lines"

        return False, None
