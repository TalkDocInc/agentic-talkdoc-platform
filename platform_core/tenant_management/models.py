"""
Tenant Data Models

Defines the core tenant data structure stored in the platform database.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TenantStatus(str, Enum):
    """Tenant lifecycle status."""

    PROVISIONING = "provisioning"  # Being created
    ACTIVE = "active"  # Fully operational
    SUSPENDED = "suspended"  # Temporarily disabled (non-payment, policy violation)
    DEACTIVATED = "deactivated"  # Permanently disabled
    MIGRATING = "migrating"  # Undergoing data migration


class SpecialtyType(str, Enum):
    """Supported healthcare specialties."""

    MENTAL_HEALTH_THERAPY = "mental_health_therapy"
    PSYCHIATRY = "psychiatry"
    PRIMARY_CARE = "primary_care"
    CARDIOLOGY = "cardiology"
    DERMATOLOGY = "dermatology"
    PHYSICAL_THERAPY = "physical_therapy"
    NUTRITION = "nutrition"
    PEDIATRICS = "pediatrics"
    WOMENS_HEALTH = "womens_health"
    URGENT_CARE = "urgent_care"


class AgentType(str, Enum):
    """Available AI agent types."""

    # Revenue Cycle Agents
    INSURANCE_VERIFICATION = "insurance_verification"
    MEDICAL_CODING = "medical_coding"
    CLAIMS_GENERATION = "claims_generation"
    DENIAL_PREDICTION = "denial_prediction"
    APPEALS_MANAGEMENT = "appeals_management"

    # Care Coordination Agents
    PATIENT_INTAKE = "patient_intake"
    SMART_SCHEDULING = "smart_scheduling"
    FOLLOWUP_COORDINATION = "followup_coordination"
    CROSS_PROVIDER_COMMUNICATION = "cross_provider_communication"
    CARE_PLAN_MANAGEMENT = "care_plan_management"

    # Patient Engagement Agents
    AI_HEALTH_ADVISOR = "ai_health_advisor"
    APPOINTMENT_ASSISTANT = "appointment_assistant"
    PATIENT_EDUCATION = "patient_education"
    SYMPTOM_ASSESSMENT = "symptom_assessment"
    OUTCOMES_TRACKING = "outcomes_tracking"


class TenantBrandingConfig(BaseModel):
    """Tenant white-label branding configuration."""

    logo_url: Optional[str] = Field(default=None, description="URL to tenant logo")
    favicon_url: Optional[str] = Field(default=None, description="URL to tenant favicon")
    primary_color: str = Field(default="#4F46E5", description="Primary brand color (hex)")
    secondary_color: str = Field(default="#06B6D4", description="Secondary brand color (hex)")
    accent_color: str = Field(default="#10B981", description="Accent color (hex)")
    font_family: str = Field(default="Inter", description="Primary font family")
    custom_css_url: Optional[str] = Field(default=None, description="URL to custom CSS")

    @field_validator("primary_color", "secondary_color", "accent_color")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        """Ensure colors are valid hex codes."""
        if not v.startswith("#") or len(v) not in [4, 7]:
            raise ValueError("Color must be a valid hex code (#RGB or #RRGGBB)")
        return v.upper()


class TenantDomainConfig(BaseModel):
    """Tenant domain and subdomain configuration."""

    primary_domain: Optional[str] = Field(default=None, description="Custom domain (e.g., talkdoc.com)")
    subdomain: str = Field(..., description="Platform subdomain (e.g., talkdoc)")
    patient_portal_url: Optional[str] = Field(default=None, description="Custom patient portal URL")
    clinician_dashboard_url: Optional[str] = Field(default=None, description="Custom clinician dashboard URL")
    coordinator_dashboard_url: Optional[str] = Field(default=None, description="Custom coordinator URL")

    @field_validator("subdomain")
    @classmethod
    def validate_subdomain(cls, v: str) -> str:
        """Ensure subdomain is URL-safe."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Subdomain must contain only alphanumeric characters, hyphens, and underscores")
        return v.lower()


class TenantFeatureConfig(BaseModel):
    """Tenant feature flags and enabled capabilities."""

    # Agent Enablement (dict of agent type to enabled status)
    enabled_agents: dict[AgentType, bool] = Field(
        default_factory=lambda: {agent: True for agent in AgentType}
    )

    # ML Models
    enable_depression_detection: bool = Field(default=False)
    enable_risk_stratification: bool = Field(default=False)

    # Video Conferencing
    enable_video_visits: bool = Field(default=True)
    video_provider: str = Field(default="aws_chime")  # aws_chime, twilio, zoom

    # Communication
    enable_sms_notifications: bool = Field(default=True)
    enable_email_notifications: bool = Field(default=True)
    enable_in_app_chat: bool = Field(default=True)

    # Billing
    enable_billing_automation: bool = Field(default=True)
    enable_payment_processing: bool = Field(default=True)
    payment_processor: str = Field(default="stripe")  # stripe, square, braintree

    # Advanced Features
    enable_multi_language: bool = Field(default=False)
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    enable_telehealth_prescribing: bool = Field(default=False)


class TenantInsuranceConfig(BaseModel):
    """Insurance and billing integration configuration."""

    clearinghouse_provider: str = Field(default="stedi")  # stedi, change_healthcare, availity
    clearinghouse_api_key: Optional[str] = Field(default=None)
    clearinghouse_account_id: Optional[str] = Field(default=None)

    accepted_insurance_plans: list[str] = Field(default_factory=list)
    require_insurance_verification: bool = Field(default=True)
    auto_verify_eligibility: bool = Field(default=True)

    organization_name: str = Field(..., description="Legal organization name")
    organization_npi: str = Field(..., description="National Provider Identifier")
    organization_tax_id: Optional[str] = Field(default=None)
    billing_address: Optional[str] = Field(default=None)


class TenantComplianceConfig(BaseModel):
    """Compliance and regulatory configuration."""

    hipaa_compliance_enabled: bool = Field(default=True)
    require_baa: bool = Field(default=True)

    licensed_states: list[str] = Field(default_factory=list, description="US states where licensed")
    require_clinician_license_verification: bool = Field(default=True)

    data_residency_region: str = Field(default="us-west-2", description="AWS region for data storage")
    enable_data_export: bool = Field(default=True)
    enable_right_to_deletion: bool = Field(default=True)

    audit_log_retention_days: int = Field(default=2555)  # 7 years


class TenantUsageLimits(BaseModel):
    """Usage limits and quotas for the tenant."""

    max_clinicians: Optional[int] = Field(default=None, description="Max clinicians (None = unlimited)")
    max_patients: Optional[int] = Field(default=None, description="Max patients (None = unlimited)")
    max_appointments_per_month: Optional[int] = Field(default=None)
    max_agent_actions_per_month: Optional[int] = Field(default=None)

    rate_limit_per_minute: int = Field(default=100)
    rate_limit_per_hour: int = Field(default=1000)


class TenantConfig(BaseModel):
    """Complete tenant configuration."""

    branding: TenantBrandingConfig = Field(default_factory=TenantBrandingConfig)
    domains: TenantDomainConfig
    features: TenantFeatureConfig = Field(default_factory=TenantFeatureConfig)
    insurance: Optional[TenantInsuranceConfig] = Field(default=None)
    compliance: TenantComplianceConfig = Field(default_factory=TenantComplianceConfig)
    usage_limits: TenantUsageLimits = Field(default_factory=TenantUsageLimits)

    # Specialty configuration
    enabled_specialties: list[SpecialtyType] = Field(default_factory=list)
    primary_specialty: Optional[SpecialtyType] = Field(default=None)

    # Custom configuration (tenant-specific overrides)
    custom_config: dict[str, Any] = Field(default_factory=dict)


class Tenant(BaseModel):
    """
    Tenant model representing a white-label customer.

    Stored in the platform database (not tenant-specific database).
    """

    tenant_id: str = Field(..., description="Unique tenant identifier")
    name: str = Field(..., description="Tenant display name")
    description: Optional[str] = Field(default=None, description="Tenant description")

    # Configuration
    config: TenantConfig

    # Database
    database_name: str = Field(..., description="MongoDB database name for this tenant")
    database_connection_string: Optional[str] = Field(
        default=None, description="Custom DB connection (if not using default)"
    )

    # Status
    status: TenantStatus = Field(default=TenantStatus.PROVISIONING)
    status_reason: Optional[str] = Field(default=None, description="Reason for current status")

    # Billing
    subscription_tier: str = Field(default="standard")  # free, standard, premium, enterprise
    monthly_fee: float = Field(default=0.0, description="Monthly subscription fee")
    per_clinician_fee: float = Field(default=100.0, description="Fee per clinician per month")
    per_agent_action_fee: float = Field(default=0.50, description="Fee per agent action")

    # Administrative
    primary_contact_email: str = Field(..., description="Primary contact for tenant")
    primary_contact_name: Optional[str] = Field(default=None)
    support_email: Optional[str] = Field(default=None)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(default=None, description="User ID who created tenant")
    last_activity_at: Optional[datetime] = Field(default=None, description="Last user activity")

    # Metrics
    total_clinicians: int = Field(default=0)
    total_patients: int = Field(default=0)
    total_appointments: int = Field(default=0)
    total_agent_actions: int = Field(default=0)

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "tenant_id": "talkdoc_prod",
                "name": "TalkDoc",
                "description": "Mental health platform for Medicaid users",
                "config": {
                    "domains": {
                        "subdomain": "talkdoc",
                        "primary_domain": "talkdoc.com",
                    },
                    "enabled_specialties": ["mental_health_therapy", "psychiatry"],
                    "primary_specialty": "mental_health_therapy",
                },
                "database_name": "talkdoc_tenant_talkdoc_prod",
                "status": "active",
                "primary_contact_email": "admin@talkdoc.com",
            }
        }
