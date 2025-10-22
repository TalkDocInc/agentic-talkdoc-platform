"""
Authentication Dependencies

FastAPI dependencies for getting current user and enforcing RBAC.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from structlog import get_logger

from ..shared_services.tenant_context import get_tenant_context
from .db_service import UserDBService
from .models import User, UserRole
from .security import decode_access_token

logger = get_logger()

# HTTP Bearer token authentication
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Get current authenticated user from JWT token.

    Args:
        credentials: Bearer token from Authorization header

    Returns:
        Current user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode token
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        logger.warning("invalid_token_decoded")
        raise credentials_exception

    # Extract user info from token
    user_id: Optional[str] = payload.get("user_id")
    tenant_id: Optional[str] = payload.get("tenant_id")

    if not user_id or not tenant_id:
        logger.warning("invalid_token_payload", user_id=user_id, tenant_id=tenant_id)
        raise credentials_exception

    # Get tenant context
    tenant_context = get_tenant_context()

    if not tenant_context:
        logger.error("no_tenant_context")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant context not available",
        )

    # Verify token tenant matches request tenant
    if tenant_id != tenant_context.tenant_id:
        logger.warning(
            "tenant_mismatch",
            token_tenant=tenant_id,
            request_tenant=tenant_context.tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token tenant does not match request tenant",
        )

    # Get user from database
    user_service = UserDBService(tenant_context.db)
    user = await user_service.get_user_by_id(user_id)

    if not user:
        logger.warning("user_not_found", user_id=user_id)
        raise credentials_exception

    # Check user is active
    if not user.is_active():
        logger.warning("inactive_user_attempt", user_id=user_id, status=user.status)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User account is {user.status}",
        )

    logger.info("user_authenticated", user_id=user_id, user_type=user.user_type)

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current active user.

    Args:
        current_user: Current user from token

    Returns:
        Current user if active

    Raises:
        HTTPException: If user is not active
    """
    if not current_user.is_active():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


def require_role(required_role: UserRole):
    """
    Dependency factory for requiring specific user role.

    Example:
        @app.get("/admin", dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))])

    Args:
        required_role: Minimum required role

    Returns:
        Dependency function
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        """
        Check if user has required role.

        Roles are hierarchical:
        PLATFORM_ADMIN > TENANT_ADMIN > MANAGER > USER > GUEST
        """
        role_hierarchy = {
            UserRole.PLATFORM_ADMIN: 5,
            UserRole.TENANT_ADMIN: 4,
            UserRole.MANAGER: 3,
            UserRole.USER: 2,
            UserRole.GUEST: 1,
        }

        user_role_level = role_hierarchy.get(current_user.role, 0)
        required_role_level = role_hierarchy.get(required_role, 0)

        if user_role_level < required_role_level:
            logger.warning(
                "insufficient_permissions",
                user_id=current_user.user_id,
                user_role=current_user.role,
                required_role=required_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )

        return current_user

    return role_checker


def require_user_type(*allowed_types: str):
    """
    Dependency factory for requiring specific user type(s).

    Example:
        @app.get("/clinician", dependencies=[Depends(require_user_type("clinician"))])

    Args:
        allowed_types: Allowed user types

    Returns:
        Dependency function
    """
    async def user_type_checker(current_user: User = Depends(get_current_user)) -> User:
        """Check if user has allowed type."""
        if current_user.user_type not in allowed_types:
            logger.warning(
                "user_type_not_allowed",
                user_id=current_user.user_id,
                user_type=current_user.user_type,
                allowed_types=allowed_types,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User type not allowed. Required: {', '.join(allowed_types)}",
            )

        return current_user

    return user_type_checker


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.

    Useful for endpoints that work for both authenticated and unauthenticated users.

    Args:
        credentials: Optional bearer token

    Returns:
        User if authenticated, None otherwise
    """
    if not credentials:
        return None

    try:
        # Try to get current user
        # We can't use get_current_user directly because it raises exceptions
        token = credentials.credentials
        payload = decode_access_token(token)

        if not payload:
            return None

        user_id = payload.get("user_id")
        tenant_id = payload.get("tenant_id")

        if not user_id or not tenant_id:
            return None

        tenant_context = get_tenant_context()
        if not tenant_context or tenant_id != tenant_context.tenant_id:
            return None

        user_service = UserDBService(tenant_context.db)
        user = await user_service.get_user_by_id(user_id)

        if user and user.is_active():
            return user

        return None

    except Exception as e:
        logger.debug("optional_auth_failed", error=str(e))
        return None
