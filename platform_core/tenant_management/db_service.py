"""
Tenant Database Service

Handles database operations for tenant management in the platform database.
"""

from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from ..config import get_config
from .models import Tenant, TenantStatus

config = get_config()


class TenantDBService:
    """
    Database service for tenant management.

    Operates on the platform database, not tenant-specific databases.
    """

    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        """
        Initialize tenant database service.

        Args:
            db: Optional database instance. If not provided, creates new connection.
        """
        if db is None:
            client = AsyncIOMotorClient(config.platform_mongo_db_url)
            self.db = client[config.platform_mongo_db_name]
        else:
            self.db = db

        self.collection = self.db["tenants"]

    async def ensure_indexes(self) -> None:
        """Create necessary indexes for tenant collection."""
        indexes = [
            IndexModel([("tenant_id", ASCENDING)], unique=True),
            IndexModel([("config.domains.subdomain", ASCENDING)], unique=True),
            IndexModel([("config.domains.primary_domain", ASCENDING)], sparse=True),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)]),
            IndexModel([("primary_contact_email", ASCENDING)]),
        ]
        await self.collection.create_indexes(indexes)

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        """
        Create a new tenant.

        Args:
            tenant: Tenant object to create

        Returns:
            Created tenant

        Raises:
            DuplicateKeyError: If tenant_id or subdomain already exists
        """
        tenant_dict = tenant.model_dump()
        tenant_dict["created_at"] = datetime.utcnow()
        tenant_dict["updated_at"] = datetime.utcnow()

        try:
            await self.collection.insert_one(tenant_dict)
            return tenant
        except DuplicateKeyError as e:
            if "tenant_id" in str(e):
                raise ValueError(f"Tenant with ID '{tenant.tenant_id}' already exists")
            elif "subdomain" in str(e):
                raise ValueError(
                    f"Subdomain '{tenant.config.domains.subdomain}' is already taken"
                )
            raise

    async def get_tenant_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """
        Get tenant by ID.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Tenant if found, None otherwise
        """
        tenant_dict = await self.collection.find_one({"tenant_id": tenant_id})
        if tenant_dict:
            return Tenant(**tenant_dict)
        return None

    async def get_tenant_by_subdomain(self, subdomain: str) -> Optional[Tenant]:
        """
        Get tenant by subdomain.

        Args:
            subdomain: Subdomain identifier

        Returns:
            Tenant if found, None otherwise
        """
        tenant_dict = await self.collection.find_one({"config.domains.subdomain": subdomain})
        if tenant_dict:
            return Tenant(**tenant_dict)
        return None

    async def get_tenant_by_domain(self, domain: str) -> Optional[Tenant]:
        """
        Get tenant by primary domain.

        Args:
            domain: Primary domain

        Returns:
            Tenant if found, None otherwise
        """
        tenant_dict = await self.collection.find_one({"config.domains.primary_domain": domain})
        if tenant_dict:
            return Tenant(**tenant_dict)
        return None

    async def update_tenant(
        self, tenant_id: str, update_data: dict, updated_by: Optional[str] = None
    ) -> Optional[Tenant]:
        """
        Update tenant information.

        Args:
            tenant_id: Tenant identifier
            update_data: Dictionary of fields to update
            updated_by: User ID performing the update

        Returns:
            Updated tenant if found, None otherwise
        """
        update_data["updated_at"] = datetime.utcnow()
        if updated_by:
            update_data["updated_by"] = updated_by

        result = await self.collection.find_one_and_update(
            {"tenant_id": tenant_id},
            {"$set": update_data},
            return_document=True,
        )

        if result:
            return Tenant(**result)
        return None

    async def update_tenant_status(
        self,
        tenant_id: str,
        status: TenantStatus,
        status_reason: Optional[str] = None,
    ) -> bool:
        """
        Update tenant status.

        Args:
            tenant_id: Tenant identifier
            status: New status
            status_reason: Optional reason for status change

        Returns:
            True if updated, False if tenant not found
        """
        update_data = {"status": status, "updated_at": datetime.utcnow()}
        if status_reason:
            update_data["status_reason"] = status_reason

        result = await self.collection.update_one(
            {"tenant_id": tenant_id}, {"$set": update_data}
        )

        return result.modified_count > 0

    async def update_tenant_metrics(
        self,
        tenant_id: str,
        total_clinicians: Optional[int] = None,
        total_patients: Optional[int] = None,
        total_appointments: Optional[int] = None,
        total_agent_actions: Optional[int] = None,
    ) -> bool:
        """
        Update tenant usage metrics.

        Args:
            tenant_id: Tenant identifier
            total_clinicians: New total clinician count
            total_patients: New total patient count
            total_appointments: New total appointment count
            total_agent_actions: New total agent action count

        Returns:
            True if updated, False if tenant not found
        """
        update_data = {"updated_at": datetime.utcnow(), "last_activity_at": datetime.utcnow()}

        if total_clinicians is not None:
            update_data["total_clinicians"] = total_clinicians
        if total_patients is not None:
            update_data["total_patients"] = total_patients
        if total_appointments is not None:
            update_data["total_appointments"] = total_appointments
        if total_agent_actions is not None:
            update_data["total_agent_actions"] = total_agent_actions

        result = await self.collection.update_one(
            {"tenant_id": tenant_id}, {"$set": update_data}
        )

        return result.modified_count > 0

    async def increment_agent_actions(self, tenant_id: str, count: int = 1) -> bool:
        """
        Increment tenant's agent action count.

        Args:
            tenant_id: Tenant identifier
            count: Number to increment by

        Returns:
            True if updated, False if tenant not found
        """
        result = await self.collection.update_one(
            {"tenant_id": tenant_id},
            {
                "$inc": {"total_agent_actions": count},
                "$set": {"updated_at": datetime.utcnow(), "last_activity_at": datetime.utcnow()},
            },
        )

        return result.modified_count > 0

    async def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Tenant]:
        """
        List tenants with optional filtering.

        Args:
            status: Filter by status
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of tenants
        """
        query = {}
        if status:
            query["status"] = status

        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)

        tenants = []
        async for tenant_dict in cursor:
            tenants.append(Tenant(**tenant_dict))

        return tenants

    async def count_tenants(self, status: Optional[TenantStatus] = None) -> int:
        """
        Count tenants.

        Args:
            status: Optional status filter

        Returns:
            Number of tenants matching criteria
        """
        query = {}
        if status:
            query["status"] = status

        return await self.collection.count_documents(query)

    async def delete_tenant(self, tenant_id: str) -> bool:
        """
        Delete a tenant (soft delete by setting status to DEACTIVATED).

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.update_one(
            {"tenant_id": tenant_id},
            {
                "$set": {
                    "status": TenantStatus.DEACTIVATED,
                    "updated_at": datetime.utcnow(),
                    "status_reason": "Tenant deleted",
                }
            },
        )

        return result.modified_count > 0

    async def hard_delete_tenant(self, tenant_id: str) -> bool:
        """
        Permanently delete a tenant record.

        WARNING: This is irreversible. Use with caution.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.delete_one({"tenant_id": tenant_id})
        return result.deleted_count > 0

    async def tenant_exists(self, tenant_id: str) -> bool:
        """
        Check if tenant exists.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if exists, False otherwise
        """
        count = await self.collection.count_documents({"tenant_id": tenant_id}, limit=1)
        return count > 0

    async def subdomain_available(self, subdomain: str) -> bool:
        """
        Check if subdomain is available.

        Args:
            subdomain: Subdomain to check

        Returns:
            True if available, False if taken
        """
        count = await self.collection.count_documents(
            {"config.domains.subdomain": subdomain}, limit=1
        )
        return count == 0
