"""
Platform Configuration Management

Centralizes all configuration for the Agentic TalkDoc platform.
Supports multiple environments (local, dev, prod) with proper secret management.
"""

import os
from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Supported deployment environments."""

    LOCAL = "local"
    DEV = "dev"
    PROD = "prod"


class PlatformConfig(BaseSettings):
    """
    Platform-wide configuration settings.

    Loads from environment variables with .env file support.
    All secrets should be injected via environment in production.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: Environment = Field(default=Environment.LOCAL)

    # Platform Database (stores tenant metadata)
    platform_mongo_db_url: str = Field(default="mongodb://localhost:27017")
    platform_mongo_db_name: str = Field(default="agentic_talkdoc_platform")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Security
    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_hours: int = Field(default=24)

    # AI/LLM Providers
    openai_api_key: Optional[str] = Field(default=None)
    anthropic_api_key: Optional[str] = Field(default=None)
    openrouter_api_key: Optional[str] = Field(default=None)

    # AWS Configuration
    aws_region: str = Field(default="us-west-2")
    aws_access_key_id: Optional[str] = Field(default=None)
    aws_secret_access_key: Optional[str] = Field(default=None)

    # AWS Services
    aws_ses_region: str = Field(default="us-west-2")
    aws_ses_from_email: str = Field(default="noreply@talkdoc.com")
    aws_chime_region: str = Field(default="us-east-1")
    aws_sqs_queue_url: Optional[str] = Field(default=None)

    # Insurance & EDI (Stedi)
    stedi_api_key: Optional[str] = Field(default=None)
    stedi_control_number: Optional[str] = Field(default=None)
    stedi_account_id: Optional[str] = Field(default=None)

    # Google OAuth
    google_client_id: Optional[str] = Field(default=None)
    google_client_secret: Optional[str] = Field(default=None)
    google_recaptcha_secret_key: Optional[str] = Field(default=None)

    # Platform URLs
    platform_api_base_url: str = Field(default="http://localhost:8000")
    admin_console_url: str = Field(default="http://localhost:3000")
    default_patient_portal_url: str = Field(default="http://localhost:3001")
    default_clinician_dashboard_url: str = Field(default="http://localhost:3002")
    default_coordinator_dashboard_url: str = Field(default="http://localhost:3003")

    # Agent Configuration
    agent_max_retries: int = Field(default=3)
    agent_timeout_seconds: int = Field(default=300)
    agent_confidence_threshold: float = Field(default=0.85)

    # Audit & Logging
    log_level: str = Field(default="INFO")
    enable_audit_logging: bool = Field(default=True)
    cloudwatch_log_group: str = Field(default="agentic-talkdoc-platform")

    # Feature Flags
    enable_agent_execution: bool = Field(default=True)
    enable_multi_agent_workflows: bool = Field(default=True)
    enable_realtime_monitoring: bool = Field(default=True)

    # Rate Limiting
    rate_limit_per_minute: int = Field(default=100)
    rate_limit_per_hour: int = Field(default=1000)

    # CORS Configuration
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003"
    )

    # Tenant Provisioning
    default_tenant_db_prefix: str = Field(default="talkdoc_tenant_")
    enable_auto_tenant_provisioning: bool = Field(default=False)

    # Billing & Usage Tracking
    enable_usage_metering: bool = Field(default=True)
    billing_cycle_day: int = Field(default=1, ge=1, le=28)

    # Compliance
    hipaa_compliance_mode: bool = Field(default=True)
    enable_phi_encryption: bool = Field(default=True)
    data_retention_days: int = Field(default=2555)  # 7 years

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret_key(cls, v: str, info) -> str:
        """Ensure secret key is properly set in non-local environments."""
        env = info.data.get("environment", Environment.LOCAL)
        if env != Environment.LOCAL and v == "change-me-in-production":
            raise ValueError("jwt_secret_key must be set in non-local environments")
        return v

    @field_validator("agent_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, v: float) -> float:
        """Ensure confidence threshold is within valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("agent_confidence_threshold must be between 0.0 and 1.0")
        return v

    def get_allowed_origins_list(self) -> list[str]:
        """Parse CORS allowed origins into a list."""
        if self.environment == Environment.LOCAL:
            return ["*"]  # Allow all in local development
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    def get_tenant_db_name(self, tenant_id: str) -> str:
        """Generate tenant-specific database name."""
        return f"{self.default_tenant_db_prefix}{tenant_id}"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PROD

    @property
    def is_local(self) -> bool:
        """Check if running in local development environment."""
        return self.environment == Environment.LOCAL


@lru_cache()
def get_config() -> PlatformConfig:
    """
    Get cached platform configuration.

    Uses lru_cache to ensure config is loaded only once.
    """
    return PlatformConfig()


# Export for easy importing
config = get_config()
