"""
Authentication API Router

REST API endpoints for user authentication and management.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from structlog import get_logger

from ..config import get_config
from ..shared_services.tenant_context import get_tenant_context
from .db_service import UserDBService
from .dependencies import get_current_user, require_role
from .models import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshTokenRequest,
    User,
    UserCreate,
    UserResponse,
    UserRole,
    UserUpdate,
)
from .security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    get_password_hash,
    validate_password_strength,
    verify_password,
    verify_password_reset_token,
    verify_refresh_token,
)

config = get_config()
logger = get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_user_service(request: Request) -> UserDBService:
    """Dependency to get user database service for current tenant."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )
    return UserDBService(tenant_context.db)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account in the current tenant",
)
async def register(
    user_create: UserCreate,
    request: Request,
    user_service: UserDBService = Depends(get_user_service),
) -> UserResponse:
    """Register a new user."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    logger.info(
        "user_registration_attempt",
        email=user_create.email,
        user_type=user_create.user_type,
        tenant_id=tenant_context.tenant_id,
    )

    # Validate password strength
    is_valid, error_message = validate_password_strength(user_create.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Check if user already exists
    existing_user = await user_service.get_user_by_email(
        user_create.email, tenant_context.tenant_id
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    # Create user
    try:
        user = await user_service.create_user(
            user_create=user_create,
            tenant_id=tenant_context.tenant_id,
        )

        logger.info(
            "user_registered",
            user_id=user.user_id,
            email=user.email,
            tenant_id=tenant_context.tenant_id,
        )

        # TODO: Send verification email

        return UserResponse(**user.model_dump())

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="User login",
    description="Authenticate user and return access token",
)
async def login(
    login_request: LoginRequest,
    user_service: UserDBService = Depends(get_user_service),
) -> LoginResponse:
    """Authenticate user and return JWT token."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    logger.info(
        "login_attempt",
        email=login_request.email,
        tenant_id=tenant_context.tenant_id,
    )

    # Get user by email
    user = await user_service.get_user_by_email(
        login_request.email, tenant_context.tenant_id
    )

    if not user:
        logger.warning("login_failed_user_not_found", email=login_request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Verify password
    if not verify_password(login_request.password, user.hashed_password):
        logger.warning("login_failed_invalid_password", user_id=user.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Check user is active
    if not user.is_active():
        logger.warning("login_failed_inactive_user", user_id=user.user_id, status=user.status)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.status}",
        )

    # Update last login
    await user_service.update_last_login(user.user_id)

    # Create access token
    token_data = {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "user_type": user.user_type,
        "role": user.role,
    }
    access_token = create_access_token(token_data)

    # Create refresh token
    refresh_token_str = create_refresh_token(user.user_id, user.tenant_id)

    logger.info("login_successful", user_id=user.user_id, user_type=user.user_type)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=config.jwt_expiry_hours * 3600,  # Convert hours to seconds
        user=UserResponse(**user.model_dump()),
    )


@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Refresh access token",
    description="Get new access token using refresh token",
)
async def refresh_token(
    refresh_request: RefreshTokenRequest,
    user_service: UserDBService = Depends(get_user_service),
) -> LoginResponse:
    """Refresh access token using refresh token."""
    # Verify refresh token
    payload = verify_refresh_token(refresh_request.refresh_token)

    if not payload:
        logger.warning("invalid_refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload.get("user_id")
    tenant_id = payload.get("tenant_id")

    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )

    # Get user
    user = await user_service.get_user_by_id(user_id)

    if not user or not user.is_active():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Create new access token
    token_data = {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "user_type": user.user_type,
        "role": user.role,
    }
    access_token = create_access_token(token_data)

    logger.info("token_refreshed", user_id=user_id)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=config.jwt_expiry_hours * 3600,
        user=UserResponse(**user.model_dump()),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get information about the currently authenticated user",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Get current user information."""
    return UserResponse(**current_user.model_dump())


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user",
    description="Update information for the currently authenticated user",
)
async def update_me(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserDBService = Depends(get_user_service),
) -> UserResponse:
    """Update current user information."""
    # Build update dictionary
    update_dict = {}
    for field, value in update_data.model_dump(exclude_unset=True).items():
        if value is not None:
            # Only admins can change their own status or role
            if field in ["status", "role"] and not current_user.is_admin():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions to update status or role",
                )
            update_dict[field] = value

    if not update_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    # Update user
    updated_user = await user_service.update_user(
        current_user.user_id, update_dict, updated_by=current_user.user_id
    )

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(
        "user_updated",
        user_id=current_user.user_id,
        fields=list(update_dict.keys()),
    )

    return UserResponse(**updated_user.model_dump())


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password",
    description="Change password for authenticated user",
)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    user_service: UserDBService = Depends(get_user_service),
) -> None:
    """Change user password."""
    # Verify current password
    if not verify_password(request.current_password, current_user.hashed_password):
        logger.warning("password_change_failed_invalid_current", user_id=current_user.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    # Validate new password strength
    is_valid, error_message = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Update password
    await user_service.update_password(current_user.user_id, request.new_password)

    logger.info("password_changed", user_id=current_user.user_id)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request password reset",
    description="Request a password reset email",
)
async def forgot_password(
    request: PasswordResetRequest,
    user_service: UserDBService = Depends(get_user_service),
) -> dict:
    """Request password reset."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Get user
    user = await user_service.get_user_by_email(request.email, tenant_context.tenant_id)

    # Don't reveal if email exists or not (security best practice)
    if not user:
        logger.warning("password_reset_requested_unknown_email", email=request.email)
        return {"message": "If the email exists, a password reset link has been sent"}

    # Create reset token
    reset_token = create_password_reset_token(user.email, user.tenant_id)
    expires = datetime.utcnow() + timedelta(minutes=30)

    # Store reset token in database
    await user_service.set_password_reset_token(user.user_id, reset_token, expires)

    # TODO: Send password reset email with token

    logger.info("password_reset_requested", user_id=user.user_id)

    return {"message": "If the email exists, a password reset link has been sent"}


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset password",
    description="Reset password using reset token",
)
async def reset_password(
    request: PasswordResetConfirm,
    user_service: UserDBService = Depends(get_user_service),
) -> None:
    """Reset password using token."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Verify reset token
    payload = verify_password_reset_token(request.token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    email = payload.get("email")
    token_tenant_id = payload.get("tenant_id")

    if not email or token_tenant_id != tenant_context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    # Get user
    user = await user_service.get_user_by_email(email, tenant_context.tenant_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Validate new password
    is_valid, error_message = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Update password
    await user_service.update_password(user.user_id, request.new_password)

    logger.info("password_reset_successful", user_id=user.user_id)


# Admin endpoints (require TENANT_ADMIN role)


@router.get(
    "/users",
    response_model=list[UserResponse],
    dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))],
    summary="List users (Admin)",
    description="List all users in the tenant (requires admin role)",
)
async def list_users(
    user_type: str = None,
    status: str = None,
    skip: int = 0,
    limit: int = 100,
    user_service: UserDBService = Depends(get_user_service),
) -> list[UserResponse]:
    """List users (admin only)."""
    tenant_context = get_tenant_context()
    if not tenant_context:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    users = await user_service.list_users(
        tenant_id=tenant_context.tenant_id,
        user_type=user_type,
        status=status,
        skip=skip,
        limit=limit,
    )

    return [UserResponse(**user.model_dump()) for user in users]


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))],
    summary="Get user by ID (Admin)",
    description="Get user details by ID (requires admin role)",
)
async def get_user_by_id(
    user_id: str,
    user_service: UserDBService = Depends(get_user_service),
) -> UserResponse:
    """Get user by ID (admin only)."""
    user = await user_service.get_user_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(**user.model_dump())


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))],
    summary="Update user (Admin)",
    description="Update user information (requires admin role)",
)
async def update_user(
    user_id: str,
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserDBService = Depends(get_user_service),
) -> UserResponse:
    """Update user (admin only)."""
    update_dict = {}
    for field, value in update_data.model_dump(exclude_unset=True).items():
        if value is not None:
            update_dict[field] = value

    if not update_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    updated_user = await user_service.update_user(
        user_id, update_dict, updated_by=current_user.user_id
    )

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(
        "user_updated_by_admin",
        user_id=user_id,
        admin_id=current_user.user_id,
        fields=list(update_dict.keys()),
    )

    return UserResponse(**updated_user.model_dump())


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))],
    summary="Delete user (Admin)",
    description="Soft delete user (requires admin role)",
)
async def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    user_service: UserDBService = Depends(get_user_service),
) -> None:
    """Delete user (admin only)."""
    # Prevent self-deletion
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    success = await user_service.delete_user(user_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info("user_deleted_by_admin", user_id=user_id, admin_id=current_user.user_id)
