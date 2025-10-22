"""
User and Authentication Models

Defines user types, roles, and the user data model.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserType(str, Enum):
    """User type classification."""

    PATIENT = "patient"
    CLINICIAN = "clinician"
    COORDINATOR = "coordinator"
    ADMIN = "admin"
    PLATFORM_ADMIN = "platform_admin"  # Super admin across all tenants


class UserRole(str, Enum):
    """
    Role-based access control roles.

    Roles are hierarchical: PLATFORM_ADMIN > TENANT_ADMIN > MANAGER > USER > GUEST
    """

    PLATFORM_ADMIN = "platform_admin"  # Full platform access
    TENANT_ADMIN = "tenant_admin"  # Full tenant access
    MANAGER = "manager"  # Management access within tenant
    USER = "user"  # Standard user access
    GUEST = "guest"  # Limited read-only access


class UserStatus(str, Enum):
    """User account status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class User(BaseModel):
    """
    User model.

    Stored in tenant-specific database (except platform admins).
    """

    user_id: str = Field(..., description="Unique user identifier")
    tenant_id: str = Field(..., description="Tenant this user belongs to")

    # Authentication
    email: EmailStr
    hashed_password: str
    password_reset_token: Optional[str] = Field(default=None)
    password_reset_expires: Optional[datetime] = Field(default=None)

    # Profile
    first_name: str
    last_name: str
    phone_number: Optional[str] = Field(default=None)
    date_of_birth: Optional[str] = Field(default=None, description="YYYY-MM-DD")

    # User classification
    user_type: UserType
    role: UserRole = Field(default=UserRole.USER)

    # Status
    status: UserStatus = Field(default=UserStatus.PENDING_VERIFICATION)
    email_verified: bool = Field(default=False)
    phone_verified: bool = Field(default=False)

    # 2FA
    two_factor_enabled: bool = Field(default=False)
    two_factor_secret: Optional[str] = Field(default=None)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = Field(default=None)
    created_by: Optional[str] = Field(default=None)

    # Additional user data (specialty-specific)
    user_info: dict = Field(default_factory=dict)

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        return f"{self.first_name} {self.last_name}"

    def is_active(self) -> bool:
        """Check if user is active."""
        return self.status == UserStatus.ACTIVE

    def is_admin(self) -> bool:
        """Check if user has admin privileges."""
        return self.role in [UserRole.TENANT_ADMIN, UserRole.PLATFORM_ADMIN]

    def is_platform_admin(self) -> bool:
        """Check if user is a platform admin."""
        return self.role == UserRole.PLATFORM_ADMIN

    def can_access_tenant(self, tenant_id: str) -> bool:
        """
        Check if user can access a specific tenant.

        Platform admins can access all tenants.
        Regular users can only access their own tenant.
        """
        if self.is_platform_admin():
            return True
        return self.tenant_id == tenant_id

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "tenant_id": "healthcareplus_20250115",
                "email": "doctor@healthcareplus.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "user_type": "clinician",
                "role": "user",
                "status": "active",
                "email_verified": True,
            }
        }


class UserCreate(BaseModel):
    """Request model for creating a new user."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone_number: Optional[str] = Field(default=None)
    user_type: UserType
    role: UserRole = Field(default=UserRole.USER)


class UserUpdate(BaseModel):
    """Request model for updating user information."""

    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone_number: Optional[str] = Field(default=None)
    status: Optional[UserStatus] = Field(default=None)
    role: Optional[UserRole] = Field(default=None)


class UserResponse(BaseModel):
    """Response model for user data (excludes sensitive fields)."""

    user_id: str
    tenant_id: str
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: Optional[str]
    user_type: UserType
    role: UserRole
    status: UserStatus
    email_verified: bool
    phone_verified: bool
    two_factor_enabled: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class TokenPayload(BaseModel):
    """JWT token payload."""

    user_id: str
    tenant_id: str
    user_type: UserType
    role: UserRole
    exp: datetime  # Expiration time


class LoginRequest(BaseModel):
    """Login request."""

    email: EmailStr
    password: str
    tenant_id: Optional[str] = Field(
        default=None, description="Optional tenant ID (can be inferred from subdomain)"
    )


class LoginResponse(BaseModel):
    """Login response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until expiration
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str


class PasswordResetRequest(BaseModel):
    """Password reset request."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation."""

    token: str
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    """Change password request (for logged-in users)."""

    current_password: str
    new_password: str = Field(..., min_length=8)
