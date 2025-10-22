"""
Tenant Management API Schemas

Request and response models for tenant management endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from .models import (
    SpecialtyType,
    TenantBrandingConfig,
    TenantComplianceConfig,
    TenantConfig,
    TenantDomainConfig,
    TenantFeatureConfig,
    TenantInsuranceConfig,
    TenantStatus,
    TenantUsageLimits,
)


class TenantCreateRequest(BaseModel):
    """Request model for creating a new tenant."""

    name: str = Field(..., min_length=2, max_length=100, description="Tenant display name")
    description: Optional[str] = Field(
        default=None, max_length=500, description="Tenant description"
    )

    # Domain configuration (required)
    subdomain: str = Field(
        ..., min_length=3, max_length=50, description="Unique subdomain identifier"
    )
    primary_domain: Optional[str] = Field(default=None, description="Custom domain")

    # Contact information (required)
    primary_contact_email: EmailStr = Field(..., description="Primary contact email")
    primary_contact_name: str = Field(..., description="Primary contact name")
    support_email: Optional[EmailStr] = Field(default=None, description="Support email")

    # Specialty configuration
    enabled_specialties: list[SpecialtyType] = Field(
        ..., min_length=1, description="At least one specialty must be enabled"
    )
    primary_specialty: SpecialtyType = Field(..., description="Primary specialty focus")

    # Optional configurations
    branding: Optional[TenantBrandingConfig] = Field(default=None)
    features: Optional[TenantFeatureConfig] = Field(default=None)
    insurance: Optional[TenantInsuranceConfig] = Field(default=None)
    compliance: Optional[TenantComplianceConfig] = Field(default=None)
    usage_limits: Optional[TenantUsageLimits] = Field(default=None)

    # Billing
    subscription_tier: str = Field(default="standard")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "HealthCare Plus",
                "description": "Primary care for insured patients",
                "subdomain": "healthcareplus",
                "primary_contact_email": "admin@healthcareplus.com",
                "primary_contact_name": "John Smith",
                "enabled_specialties": ["primary_care"],
                "primary_specialty": "primary_care",
                "subscription_tier": "premium",
            }
        }


class TenantUpdateRequest(BaseModel):
    """Request model for updating an existing tenant."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)

    # Contact updates
    primary_contact_email: Optional[EmailStr] = Field(default=None)
    primary_contact_name: Optional[str] = Field(default=None)
    support_email: Optional[EmailStr] = Field(default=None)

    # Configuration updates
    branding: Optional[TenantBrandingConfig] = Field(default=None)
    domains: Optional[TenantDomainConfig] = Field(default=None)
    features: Optional[TenantFeatureConfig] = Field(default=None)
    insurance: Optional[TenantInsuranceConfig] = Field(default=None)
    compliance: Optional[TenantComplianceConfig] = Field(default=None)
    usage_limits: Optional[TenantUsageLimits] = Field(default=None)

    # Specialty updates
    enabled_specialties: Optional[list[SpecialtyType]] = Field(default=None)
    primary_specialty: Optional[SpecialtyType] = Field(default=None)

    # Status updates
    status: Optional[TenantStatus] = Field(default=None)
    status_reason: Optional[str] = Field(default=None)


class TenantResponse(BaseModel):
    """Response model for tenant data."""

    tenant_id: str
    name: str
    description: Optional[str]

    config: TenantConfig
    database_name: str

    status: TenantStatus
    status_reason: Optional[str]

    subscription_tier: str
    monthly_fee: float
    per_clinician_fee: float
    per_agent_action_fee: float

    primary_contact_email: str
    primary_contact_name: Optional[str]
    support_email: Optional[str]

    created_at: datetime
    updated_at: datetime
    last_activity_at: Optional[datetime]

    total_clinicians: int
    total_patients: int
    total_appointments: int
    total_agent_actions: int


class TenantListResponse(BaseModel):
    """Response model for listing tenants."""

    tenants: list[TenantResponse]
    total: int
    page: int
    page_size: int


class TenantProvisioningResponse(BaseModel):
    """Response model for tenant provisioning status."""

    tenant_id: str
    status: TenantStatus
    message: str
    provisioning_steps: list[dict[str, str]]
    completed_steps: int
    total_steps: int
    estimated_completion_seconds: Optional[int] = None


class TenantUsageStatsResponse(BaseModel):
    """Response model for tenant usage statistics."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    # User metrics
    active_clinicians: int
    active_patients: int
    new_patients: int

    # Appointment metrics
    total_appointments: int
    completed_appointments: int
    cancelled_appointments: int
    no_show_appointments: int

    # Agent metrics
    total_agent_actions: int
    agent_actions_by_type: dict[str, int]
    agent_success_rate: float
    agent_cost: float

    # Revenue cycle metrics
    claims_submitted: int
    claims_paid: int
    claims_denied: int
    denial_rate: float
    average_days_to_payment: float

    # Financial metrics
    subscription_charges: float
    per_clinician_charges: float
    agent_action_charges: float
    total_charges: float


class TenantHealthCheckResponse(BaseModel):
    """Response model for tenant health check."""

    tenant_id: str
    status: str  # healthy, degraded, unhealthy
    database_connected: bool
    redis_connected: bool
    agent_orchestrator_running: bool
    last_agent_execution: Optional[datetime]
    error_rate_last_hour: float
    average_response_time_ms: float
    issues: list[str] = Field(default_factory=list)
