"""
Tenant Context Management

Provides request-scoped tenant context for database routing and configuration access.
"""

from contextvars import ContextVar
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ..tenant_management.models import Tenant

# Context variable to store current tenant for the request
_tenant_context: ContextVar[Optional["TenantContext"]] = ContextVar(
    "tenant_context", default=None
)


class TenantContext:
    """
    Tenant context for a request.

    Provides access to tenant information and database connection.
    """

    def __init__(
        self,
        tenant: Tenant,
        db: AsyncIOMotorDatabase,
        mongo_client: AsyncIOMotorClient,
    ):
        """
        Initialize tenant context.

        Args:
            tenant: Tenant object
            db: Tenant-specific database connection
            mongo_client: MongoDB client instance
        """
        self.tenant = tenant
        self.db = db
        self.mongo_client = mongo_client

    @property
    def tenant_id(self) -> str:
        """Get tenant ID."""
        return self.tenant.tenant_id

    @property
    def database_name(self) -> str:
        """Get database name."""
        return self.tenant.database_name

    @property
    def config(self):
        """Get tenant configuration."""
        return self.tenant.config

    def is_agent_enabled(self, agent_type: str) -> bool:
        """
        Check if a specific agent is enabled for this tenant.

        Args:
            agent_type: Agent type identifier

        Returns:
            True if agent is enabled
        """
        return self.config.features.enabled_agents.get(agent_type, False)

    def is_feature_enabled(self, feature_name: str) -> bool:
        """
        Check if a feature is enabled for this tenant.

        Args:
            feature_name: Feature name

        Returns:
            True if feature is enabled
        """
        return getattr(self.config.features, f"enable_{feature_name}", False)


def set_tenant_context(context: TenantContext) -> None:
    """
    Set the tenant context for the current request.

    Args:
        context: Tenant context to set
    """
    _tenant_context.set(context)


def get_tenant_context() -> Optional[TenantContext]:
    """
    Get the tenant context for the current request.

    Returns:
        Tenant context if set, None otherwise
    """
    return _tenant_context.get()


def clear_tenant_context() -> None:
    """Clear the tenant context."""
    _tenant_context.set(None)
