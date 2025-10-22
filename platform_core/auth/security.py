"""
Security Utilities

Password hashing with Argon2id and JWT token management.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from structlog import get_logger

from ..config import get_config

config = get_config()
logger = get_logger()

# Password hashing context with Argon2id (recommended by OWASP)
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],  # Argon2 preferred, bcrypt for legacy
    deprecated="auto",
    argon2__memory_cost=65536,  # 64 MB
    argon2__time_cost=3,  # 3 iterations
    argon2__parallelism=4,  # 4 parallel threads
)


def get_password_hash(password: str) -> str:
    """
    Hash a password using Argon2id.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Supports both Argon2id and bcrypt (for legacy passwords).

    Args:
        plain_password: Plain text password to verify
        hashed_password: Stored password hash

    Returns:
        True if password matches, False otherwise
    """
    try:
        # Verify password
        verified, needs_rehash = pwd_context.verify_and_update(plain_password, hashed_password)

        if needs_rehash:
            # Password is correct but uses deprecated algorithm (bcrypt)
            # Should be rehashed to Argon2id on next login
            logger.info("password_needs_rehash", algorithm="bcrypt_to_argon2")

        return verified
    except Exception as e:
        logger.error("password_verification_error", error=str(e))
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token
        expires_delta: Token expiration time (defaults to config value)

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    # Set expiration
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=config.jwt_expiry_hours)

    to_encode.update({"exp": expire})

    # Encode JWT
    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )

    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT access token.

    Args:
        token: JWT token to decode

    Returns:
        Token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=[config.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.warning("jwt_decode_error", error=str(e))
        return None


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    """
    Create a refresh token with longer expiration.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier

    Returns:
        Encoded refresh token
    """
    data = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "type": "refresh",
    }

    # Refresh tokens expire after 30 days
    expire = datetime.utcnow() + timedelta(days=30)
    data.update({"exp": expire})

    encoded_jwt = jwt.encode(
        data,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )

    return encoded_jwt


def verify_refresh_token(token: str) -> Optional[dict[str, Any]]:
    """
    Verify a refresh token.

    Args:
        token: Refresh token to verify

    Returns:
        Token payload if valid and type is 'refresh', None otherwise
    """
    payload = decode_access_token(token)

    if payload and payload.get("type") == "refresh":
        return payload

    return None


def create_password_reset_token(email: str, tenant_id: str) -> str:
    """
    Create a password reset token.

    Args:
        email: User email
        tenant_id: Tenant identifier

    Returns:
        Encoded reset token (expires in 30 minutes)
    """
    data = {
        "email": email,
        "tenant_id": tenant_id,
        "type": "password_reset",
    }

    # Reset tokens expire after 30 minutes
    expire = datetime.utcnow() + timedelta(minutes=30)
    data.update({"exp": expire})

    encoded_jwt = jwt.encode(
        data,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )

    return encoded_jwt


def verify_password_reset_token(token: str) -> Optional[dict[str, Any]]:
    """
    Verify a password reset token.

    Args:
        token: Reset token to verify

    Returns:
        Token payload if valid and type is 'password_reset', None otherwise
    """
    payload = decode_access_token(token)

    if payload and payload.get("type") == "password_reset":
        return payload

    return None


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password strength.

    Requirements:
    - At least 8 characters
    - Contains uppercase letter
    - Contains lowercase letter
    - Contains digit
    - Contains special character

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"

    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"

    return True, None
