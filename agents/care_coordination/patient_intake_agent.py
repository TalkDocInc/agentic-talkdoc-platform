"""
Patient Intake Agent

Automates patient onboarding and information collection process.

This agent:
1. Validates patient demographic information
2. Verifies insurance information completeness
3. Collects medical history and consent forms
4. Identifies missing required fields
5. Creates structured patient profile ready for EHR entry
6. Sends welcome communications
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

from platform_core.agent_orchestration.base_agent import BaseAgent
from platform_core.config import get_config
from platform_core.shared_services.tenant_context import get_tenant_context

config = get_config()


class PatientDemographics(BaseModel):
    """Patient demographic information."""

    first_name: str
    last_name: str
    date_of_birth: str = Field(..., description="YYYY-MM-DD format")
    gender: Optional[str] = Field(default=None)
    email: EmailStr
    phone_number: str
    address: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    zip_code: Optional[str] = Field(default=None)
    emergency_contact_name: Optional[str] = Field(default=None)
    emergency_contact_phone: Optional[str] = Field(default=None)


class InsuranceInformation(BaseModel):
    """Patient insurance information."""

    has_insurance: bool
    insurance_provider: Optional[str] = Field(default=None)
    member_id: Optional[str] = Field(default=None)
    group_number: Optional[str] = Field(default=None)
    policy_holder_name: Optional[str] = Field(default=None)
    policy_holder_dob: Optional[str] = Field(default=None)
    insurance_phone: Optional[str] = Field(default=None)


class MedicalHistory(BaseModel):
    """Patient medical history."""

    primary_reason_for_visit: str
    current_medications: Optional[list[str]] = Field(default_factory=list)
    allergies: Optional[list[str]] = Field(default_factory=list)
    chronic_conditions: Optional[list[str]] = Field(default_factory=list)
    previous_surgeries: Optional[list[str]] = Field(default_factory=list)
    family_history: Optional[str] = Field(default=None)
    social_history: Optional[str] = Field(default=None)


class ConsentForms(BaseModel):
    """Patient consent and acknowledgment forms."""

    hipaa_authorization: bool = Field(default=False)
    treatment_consent: bool = Field(default=False)
    telehealth_consent: bool = Field(default=False)
    privacy_policy_acknowledged: bool = Field(default=False)
    financial_responsibility_acknowledged: bool = Field(default=False)


class PatientIntakeInput(BaseModel):
    """Input for patient intake agent."""

    demographics: PatientDemographics
    insurance: Optional[InsuranceInformation] = Field(default=None)
    medical_history: Optional[MedicalHistory] = Field(default=None)
    consents: Optional[ConsentForms] = Field(default=None)

    # Additional context
    preferred_language: str = Field(default="en")
    how_did_you_hear_about_us: Optional[str] = Field(default=None)
    preferred_appointment_times: Optional[list[str]] = Field(default=None)


class ValidationIssue(BaseModel):
    """Validation issue found during intake."""

    field: str
    severity: str = Field(..., description="error, warning, or info")
    message: str
    suggested_action: Optional[str] = Field(default=None)


class PatientIntakeOutput(BaseModel):
    """Output from patient intake agent."""

    # Validation results
    is_complete: bool = Field(
        description="Is all required information collected?"
    )
    completeness_percentage: float = Field(
        ge=0.0, le=100.0, description="Percentage of required fields completed"
    )

    # Missing information
    missing_required_fields: list[str] = Field(default_factory=list)
    missing_optional_fields: list[str] = Field(default_factory=list)

    # Validation issues
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    errors: int = Field(default=0, description="Number of errors found")
    warnings: int = Field(default=0, description="Number of warnings")

    # Patient profile
    patient_profile_created: bool = Field(default=False)
    patient_id: Optional[str] = Field(default=None, description="Generated patient ID if created")

    # Next steps
    next_steps: list[str] = Field(
        default_factory=list, description="What patient needs to do next"
    )
    ready_for_scheduling: bool = Field(
        default=False, description="Can patient schedule appointment?"
    )

    # Communication
    welcome_email_sent: bool = Field(default=False)
    verification_needed: bool = Field(default=False)

    # Summary
    intake_summary: str = Field(..., description="Summary of intake process")


class PatientIntakeAgent(BaseAgent[PatientIntakeInput, PatientIntakeOutput]):
    """
    Agent that processes patient intake and onboarding.

    Validates information completeness and creates patient profile.
    """

    def __init__(self):
        """Initialize patient intake agent."""
        super().__init__(
            agent_type="patient_intake",
            agent_version="1.0.0",
            max_retries=1,  # Intake validation doesn't need retries
            timeout_seconds=30,
        )

    async def _execute_internal(
        self,
        input_data: PatientIntakeInput,
        context: dict[str, Any],
    ) -> tuple[PatientIntakeOutput, float, dict[str, Any]]:
        """
        Execute patient intake validation and processing.

        Args:
            input_data: Patient information
            context: Execution context

        Returns:
            Tuple of (output, confidence, metrics)
        """
        # Track metrics (no API calls for this agent)
        api_calls_made = 0
        tokens_used = 0
        cost_usd = 0.0

        try:
            # Step 1: Validate demographics
            demo_issues = self._validate_demographics(input_data.demographics)

            # Step 2: Validate insurance (if provided)
            insurance_issues = []
            if input_data.insurance:
                insurance_issues = self._validate_insurance(input_data.insurance)

            # Step 3: Validate medical history (if provided)
            history_issues = []
            if input_data.medical_history:
                history_issues = self._validate_medical_history(input_data.medical_history)

            # Step 4: Validate consents (if provided)
            consent_issues = []
            if input_data.consents:
                consent_issues = self._validate_consents(input_data.consents)

            # Combine all validation issues
            all_issues = demo_issues + insurance_issues + history_issues + consent_issues

            # Count errors and warnings
            errors = sum(1 for issue in all_issues if issue.severity == "error")
            warnings = sum(1 for issue in all_issues if issue.severity == "warning")

            # Step 5: Calculate completeness
            completeness_pct, missing_required, missing_optional = self._calculate_completeness(
                input_data
            )

            # Step 6: Determine if intake is complete
            is_complete = errors == 0 and len(missing_required) == 0

            # Step 7: Determine if ready for scheduling
            ready_for_scheduling = (
                is_complete
                and input_data.consents
                and input_data.consents.hipaa_authorization
                and input_data.consents.treatment_consent
            )

            # Step 8: Generate next steps
            next_steps = self._generate_next_steps(
                is_complete, missing_required, all_issues, input_data.consents
            )

            # Step 9: Create patient profile (if complete enough)
            patient_profile_created = False
            patient_id = None
            if completeness_pct >= 75:  # Minimum 75% complete
                patient_profile_created = True
                patient_id = self._generate_patient_id()
                # TODO: Actually create patient in database

            # Step 10: Generate summary
            intake_summary = self._generate_summary(
                input_data, is_complete, completeness_pct, errors, warnings
            )

            # Step 11: Determine if verification needed
            verification_needed = (
                input_data.insurance is not None
                and input_data.insurance.has_insurance
                and not any(issue.field.startswith("insurance") and issue.severity == "error" for issue in all_issues)
            )

            output = PatientIntakeOutput(
                is_complete=is_complete,
                completeness_percentage=completeness_pct,
                missing_required_fields=missing_required,
                missing_optional_fields=missing_optional,
                validation_issues=all_issues,
                errors=errors,
                warnings=warnings,
                patient_profile_created=patient_profile_created,
                patient_id=patient_id,
                next_steps=next_steps,
                ready_for_scheduling=ready_for_scheduling,
                welcome_email_sent=False,  # TODO: Integrate with email service
                verification_needed=verification_needed,
                intake_summary=intake_summary,
            )

            # Calculate confidence based on completeness and validation
            confidence = self._calculate_confidence(output)

            metrics = {
                "api_calls_made": api_calls_made,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }

            return output, confidence, metrics

        except Exception as e:
            self.logger.error("patient_intake_error", error=str(e))

            # Return error output
            output = PatientIntakeOutput(
                is_complete=False,
                completeness_percentage=0.0,
                validation_issues=[
                    ValidationIssue(
                        field="system",
                        severity="error",
                        message=f"Intake processing error: {str(e)}",
                    )
                ],
                errors=1,
                intake_summary=f"Error processing intake: {str(e)}",
            )

            metrics = {
                "api_calls_made": 0,
                "tokens_used": 0,
                "cost_usd": 0.0,
            }

            return output, 0.0, metrics

    def _validate_demographics(self, demographics: PatientDemographics) -> list[ValidationIssue]:
        """Validate demographic information."""
        issues = []

        # Validate date of birth format and age
        try:
            dob = datetime.strptime(demographics.date_of_birth, "%Y-%m-%d")
            age = (datetime.utcnow() - dob).days // 365

            if age < 0:
                issues.append(
                    ValidationIssue(
                        field="date_of_birth",
                        severity="error",
                        message="Date of birth cannot be in the future",
                    )
                )
            elif age > 120:
                issues.append(
                    ValidationIssue(
                        field="date_of_birth",
                        severity="warning",
                        message=f"Age ({age}) seems unusually high. Please verify.",
                    )
                )
        except ValueError:
            issues.append(
                ValidationIssue(
                    field="date_of_birth",
                    severity="error",
                    message="Invalid date format. Use YYYY-MM-DD",
                )
            )

        # Validate phone number format (basic)
        if not demographics.phone_number.replace("+", "").replace("-", "").replace(" ", "").isdigit():
            issues.append(
                ValidationIssue(
                    field="phone_number",
                    severity="warning",
                    message="Phone number format may be invalid",
                    suggested_action="Verify phone number is correct",
                )
            )

        # Check for complete address
        address_fields = [demographics.address, demographics.city, demographics.state, demographics.zip_code]
        if any(address_fields) and not all(address_fields):
            issues.append(
                ValidationIssue(
                    field="address",
                    severity="warning",
                    message="Incomplete address information",
                    suggested_action="Provide complete address (street, city, state, zip)",
                )
            )

        return issues

    def _validate_insurance(self, insurance: InsuranceInformation) -> list[ValidationIssue]:
        """Validate insurance information."""
        issues = []

        if insurance.has_insurance:
            # Check required insurance fields
            if not insurance.insurance_provider:
                issues.append(
                    ValidationIssue(
                        field="insurance_provider",
                        severity="error",
                        message="Insurance provider is required when patient has insurance",
                    )
                )

            if not insurance.member_id:
                issues.append(
                    ValidationIssue(
                        field="insurance.member_id",
                        severity="error",
                        message="Insurance member ID is required",
                    )
                )

            if not insurance.policy_holder_name:
                issues.append(
                    ValidationIssue(
                        field="insurance.policy_holder_name",
                        severity="warning",
                        message="Policy holder name is recommended",
                    )
                )

        return issues

    def _validate_medical_history(self, history: MedicalHistory) -> list[ValidationIssue]:
        """Validate medical history."""
        issues = []

        # Ensure primary reason is provided
        if not history.primary_reason_for_visit or len(history.primary_reason_for_visit) < 10:
            issues.append(
                ValidationIssue(
                    field="medical_history.primary_reason_for_visit",
                    severity="warning",
                    message="Primary reason for visit should be more detailed",
                    suggested_action="Provide a clear description of the reason for seeking care",
                )
            )

        return issues

    def _validate_consents(self, consents: ConsentForms) -> list[ValidationIssue]:
        """Validate consent forms."""
        issues = []

        # Check required consents
        if not consents.hipaa_authorization:
            issues.append(
                ValidationIssue(
                    field="consents.hipaa_authorization",
                    severity="error",
                    message="HIPAA authorization is required",
                )
            )

        if not consents.treatment_consent:
            issues.append(
                ValidationIssue(
                    field="consents.treatment_consent",
                    severity="error",
                    message="Treatment consent is required",
                )
            )

        if not consents.privacy_policy_acknowledged:
            issues.append(
                ValidationIssue(
                    field="consents.privacy_policy_acknowledged",
                    severity="warning",
                    message="Privacy policy should be acknowledged",
                )
            )

        return issues

    def _calculate_completeness(
        self, input_data: PatientIntakeInput
    ) -> tuple[float, list[str], list[str]]:
        """Calculate intake completeness percentage."""
        # Required fields
        required_fields = [
            ("demographics", input_data.demographics is not None),
            ("demographics.first_name", bool(input_data.demographics.first_name)),
            ("demographics.last_name", bool(input_data.demographics.last_name)),
            ("demographics.date_of_birth", bool(input_data.demographics.date_of_birth)),
            ("demographics.email", bool(input_data.demographics.email)),
            ("demographics.phone_number", bool(input_data.demographics.phone_number)),
            ("medical_history.primary_reason", input_data.medical_history is not None and bool(input_data.medical_history.primary_reason_for_visit)),
            ("consents.hipaa", input_data.consents is not None and input_data.consents.hipaa_authorization),
            ("consents.treatment", input_data.consents is not None and input_data.consents.treatment_consent),
        ]

        # Optional fields
        optional_fields = [
            ("demographics.address", input_data.demographics.address is not None),
            ("demographics.emergency_contact", input_data.demographics.emergency_contact_name is not None),
            ("insurance", input_data.insurance is not None),
            ("medical_history.medications", input_data.medical_history is not None and bool(input_data.medical_history.current_medications)),
            ("medical_history.allergies", input_data.medical_history is not None and bool(input_data.medical_history.allergies)),
            ("consents.telehealth", input_data.consents is not None and input_data.consents.telehealth_consent),
        ]

        # Calculate percentages
        required_complete = sum(1 for _, complete in required_fields if complete)
        optional_complete = sum(1 for _, complete in optional_fields if complete)

        total_fields = len(required_fields) + len(optional_fields)
        total_complete = required_complete + optional_complete

        completeness_pct = (total_complete / total_fields) * 100

        # Get missing fields
        missing_required = [field for field, complete in required_fields if not complete]
        missing_optional = [field for field, complete in optional_fields if not complete]

        return completeness_pct, missing_required, missing_optional

    def _generate_next_steps(
        self,
        is_complete: bool,
        missing_required: list[str],
        issues: list[ValidationIssue],
        consents: Optional[ConsentForms],
    ) -> list[str]:
        """Generate next steps for patient."""
        next_steps = []

        if missing_required:
            next_steps.append(f"Complete {len(missing_required)} required field(s)")

        # Check for errors
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            next_steps.append(f"Fix {len(errors)} error(s) in your information")

        # Check consents
        if consents:
            if not consents.hipaa_authorization:
                next_steps.append("Sign HIPAA authorization form")
            if not consents.treatment_consent:
                next_steps.append("Sign treatment consent form")
        else:
            next_steps.append("Complete required consent forms")

        if is_complete:
            next_steps = ["Schedule your first appointment", "Check your email for welcome message"]

        return next_steps

    def _generate_patient_id(self) -> str:
        """Generate unique patient ID."""
        from uuid import uuid4

        return f"PAT_{str(uuid4())[:8].upper()}"

    def _generate_summary(
        self,
        input_data: PatientIntakeInput,
        is_complete: bool,
        completeness_pct: float,
        errors: int,
        warnings: int,
    ) -> str:
        """Generate intake summary."""
        patient_name = f"{input_data.demographics.first_name} {input_data.demographics.last_name}"

        if is_complete:
            summary = f"Intake complete for {patient_name}. Patient profile created and ready for scheduling."
        else:
            summary = f"Intake {completeness_pct:.0f}% complete for {patient_name}."

            if errors > 0:
                summary += f" {errors} error(s) need to be resolved."
            if warnings > 0:
                summary += f" {warnings} warning(s) to review."

        return summary

    def _calculate_confidence(self, output: PatientIntakeOutput) -> float:
        """Calculate confidence in intake validation."""
        # Base confidence on completeness and lack of errors
        confidence = output.completeness_percentage / 100.0

        # Reduce confidence for errors
        if output.errors > 0:
            confidence *= 0.5

        # Slightly reduce for warnings
        if output.warnings > 0:
            confidence *= 0.9

        # High confidence if complete
        if output.is_complete:
            confidence = max(confidence, 0.95)

        return max(0.0, min(1.0, confidence))
