"""
Tenant Provisioning Service

Handles the complete provisioning workflow for new tenants:
1. Create tenant record in platform database
2. Create tenant-specific database
3. Initialize collections and indexes
4. Set up initial configuration
5. Create default admin user
"""

import secrets
import string
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from structlog import get_logger

from ..config import get_config
from .db_service import TenantDBService
from .models import (
    SpecialtyType,
    Tenant,
    TenantBrandingConfig,
    TenantComplianceConfig,
    TenantConfig,
    TenantDomainConfig,
    TenantFeatureConfig,
    TenantStatus,
    TenantUsageLimits,
)
from .schema import TenantCreateRequest

config = get_config()
logger = get_logger()


class TenantProvisioningService:
    """Service for provisioning new tenants."""

    def __init__(self, tenant_db_service: Optional[TenantDBService] = None):
        """
        Initialize provisioning service.

        Args:
            tenant_db_service: Optional tenant DB service instance
        """
        self.tenant_db_service = tenant_db_service or TenantDBService()
        self.mongo_client = AsyncIOMotorClient(config.platform_mongo_db_url)

    def _generate_tenant_id(self, subdomain: str) -> str:
        """
        Generate unique tenant ID from subdomain.

        Args:
            subdomain: Tenant subdomain

        Returns:
            Tenant ID
        """
        # Use subdomain as base, add timestamp for uniqueness
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        return f"{subdomain}_{timestamp}"

    def _generate_secure_password(self, length: int = 16) -> str:
        """
        Generate a secure random password.

        Args:
            length: Password length

        Returns:
            Secure random password
        """
        alphabet = string.ascii_letters + string.digits + string.punctuation
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def provision_tenant(
        self,
        request: TenantCreateRequest,
        created_by: Optional[str] = None,
    ) -> Tenant:
        """
        Provision a new tenant with complete setup.

        Args:
            request: Tenant creation request
            created_by: User ID creating the tenant

        Returns:
            Provisioned tenant

        Raises:
            ValueError: If subdomain is taken or validation fails
        """
        logger.info("starting_tenant_provisioning", subdomain=request.subdomain)

        # Step 1: Validate subdomain availability
        if not await self.tenant_db_service.subdomain_available(request.subdomain):
            raise ValueError(f"Subdomain '{request.subdomain}' is already taken")

        # Step 2: Generate tenant ID
        tenant_id = self._generate_tenant_id(request.subdomain)
        logger.info("generated_tenant_id", tenant_id=tenant_id)

        # Step 3: Build tenant configuration
        domain_config = TenantDomainConfig(
            subdomain=request.subdomain,
            primary_domain=request.primary_domain,
        )

        tenant_config = TenantConfig(
            branding=request.branding or TenantBrandingConfig(),
            domains=domain_config,
            features=request.features or TenantFeatureConfig(),
            insurance=request.insurance,
            compliance=request.compliance or TenantComplianceConfig(),
            usage_limits=request.usage_limits or TenantUsageLimits(),
            enabled_specialties=request.enabled_specialties,
            primary_specialty=request.primary_specialty,
        )

        # Step 4: Create tenant object
        database_name = config.get_tenant_db_name(tenant_id)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=request.name,
            description=request.description,
            config=tenant_config,
            database_name=database_name,
            status=TenantStatus.PROVISIONING,
            subscription_tier=request.subscription_tier,
            primary_contact_email=request.primary_contact_email,
            primary_contact_name=request.primary_contact_name,
            support_email=request.support_email,
            created_by=created_by,
        )

        # Step 5: Create tenant record in platform database
        try:
            await self.tenant_db_service.create_tenant(tenant)
            logger.info("created_tenant_record", tenant_id=tenant_id)
        except Exception as e:
            logger.error("failed_to_create_tenant_record", tenant_id=tenant_id, error=str(e))
            raise

        # Step 6: Create tenant-specific database
        try:
            await self._create_tenant_database(tenant_id, database_name)
            logger.info("created_tenant_database", tenant_id=tenant_id, database=database_name)
        except Exception as e:
            logger.error(
                "failed_to_create_tenant_database",
                tenant_id=tenant_id,
                error=str(e),
            )
            # Rollback: delete tenant record
            await self.tenant_db_service.hard_delete_tenant(tenant_id)
            raise

        # Step 7: Initialize tenant database schema
        try:
            await self._initialize_tenant_schema(database_name)
            logger.info("initialized_tenant_schema", tenant_id=tenant_id)
        except Exception as e:
            logger.error(
                "failed_to_initialize_tenant_schema",
                tenant_id=tenant_id,
                error=str(e),
            )
            # Rollback: delete database and tenant record
            await self._delete_tenant_database(database_name)
            await self.tenant_db_service.hard_delete_tenant(tenant_id)
            raise

        # Step 8: Mark tenant as active
        await self.tenant_db_service.update_tenant_status(
            tenant_id, TenantStatus.ACTIVE, "Provisioning completed successfully"
        )

        logger.info(
            "tenant_provisioning_completed",
            tenant_id=tenant_id,
            subdomain=request.subdomain,
        )

        # Return updated tenant
        updated_tenant = await self.tenant_db_service.get_tenant_by_id(tenant_id)
        return updated_tenant or tenant

    async def _create_tenant_database(self, tenant_id: str, database_name: str) -> None:
        """
        Create a new database for the tenant.

        Args:
            tenant_id: Tenant identifier
            database_name: Database name to create
        """
        # MongoDB creates databases on first write
        # We'll create an initialization collection to ensure DB exists
        tenant_db = self.mongo_client[database_name]
        init_collection = tenant_db["_initialization"]

        await init_collection.insert_one(
            {
                "tenant_id": tenant_id,
                "initialized_at": datetime.utcnow(),
                "schema_version": "1.0.0",
            }
        )

        logger.info(
            "tenant_database_created",
            tenant_id=tenant_id,
            database=database_name,
        )

    async def _initialize_tenant_schema(self, database_name: str) -> None:
        """
        Initialize all collections and indexes for a tenant database.

        Args:
            database_name: Database name to initialize
        """
        from pymongo import ASCENDING, DESCENDING, IndexModel

        tenant_db = self.mongo_client[database_name]

        # Define collections and their indexes
        collection_indexes = {
            "users": [
                IndexModel([("user_id", ASCENDING)], unique=True),
                IndexModel([("email", ASCENDING)], unique=True, sparse=True),
                IndexModel([("user_type", ASCENDING)]),
                IndexModel([("created_at", DESCENDING)]),
            ],
            "appointments": [
                IndexModel([("appointment_id", ASCENDING)], unique=True),
                IndexModel([("client_user_id", ASCENDING)]),
                IndexModel([("clinician_user_id", ASCENDING)]),
                IndexModel([("start_timestamp", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("created_at", DESCENDING)]),
            ],
            "availabilities": [
                IndexModel([("availability_id", ASCENDING)], unique=True),
                IndexModel([("clinician_user_id", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
            ],
            "chime_meetings": [
                IndexModel([("meeting_id", ASCENDING)], unique=True),
                IndexModel([("appointment_id", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
            ],
            "agent_audit_logs": [
                IndexModel([("log_id", ASCENDING)], unique=True),
                IndexModel([("agent_type", ASCENDING)]),
                IndexModel([("executed_at", DESCENDING)]),
                IndexModel([("user_id", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
            ],
            "agent_tasks": [
                IndexModel([("task_id", ASCENDING)], unique=True),
                IndexModel([("agent_type", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("created_at", DESCENDING)]),
                IndexModel([("scheduled_for", ASCENDING)]),
            ],
        }

        # Create collections with indexes
        for collection_name, indexes in collection_indexes.items():
            collection = tenant_db[collection_name]
            if indexes:
                await collection.create_indexes(indexes)

        logger.info(
            "tenant_schema_initialized",
            database=database_name,
            collections=len(collection_indexes),
        )

    async def _delete_tenant_database(self, database_name: str) -> None:
        """
        Delete a tenant database (used for rollback).

        Args:
            database_name: Database name to delete
        """
        await self.mongo_client.drop_database(database_name)
        logger.warning("tenant_database_deleted", database=database_name)

    async def deprovision_tenant(self, tenant_id: str) -> bool:
        """
        Deprovision a tenant (deactivate and optionally delete data).

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if deprovisioned successfully
        """
        logger.info("starting_tenant_deprovisioning", tenant_id=tenant_id)

        # Get tenant info
        tenant = await self.tenant_db_service.get_tenant_by_id(tenant_id)
        if not tenant:
            logger.error("tenant_not_found", tenant_id=tenant_id)
            return False

        # Mark as deactivated
        await self.tenant_db_service.update_tenant_status(
            tenant_id, TenantStatus.DEACTIVATED, "Tenant deprovisioned"
        )

        logger.info("tenant_deprovisioned", tenant_id=tenant_id)
        return True

    async def migrate_tenant_data(
        self,
        tenant_id: str,
        source_database: str,
    ) -> bool:
        """
        Migrate existing data into a tenant database.

        Args:
            tenant_id: Tenant identifier
            source_database: Source database name to migrate from

        Returns:
            True if migration successful
        """
        logger.info(
            "starting_tenant_migration",
            tenant_id=tenant_id,
            source_database=source_database,
        )

        # Update tenant status to migrating
        await self.tenant_db_service.update_tenant_status(
            tenant_id, TenantStatus.MIGRATING, "Data migration in progress"
        )

        try:
            tenant = await self.tenant_db_service.get_tenant_by_id(tenant_id)
            if not tenant:
                raise ValueError(f"Tenant {tenant_id} not found")

            # Get source and destination databases
            source_db = self.mongo_client[source_database]
            dest_db = self.mongo_client[tenant.database_name]

            # Define collections to migrate
            collections_to_migrate = [
                "users",
                "appointments",
                "availabilities",
                "chime_meetings",
            ]

            # Migrate each collection
            for collection_name in collections_to_migrate:
                source_collection = source_db[collection_name]
                dest_collection = dest_db[collection_name]

                # Get all documents from source
                cursor = source_collection.find({})
                documents = await cursor.to_list(length=None)

                if documents:
                    # Insert into destination
                    await dest_collection.insert_many(documents)
                    logger.info(
                        "migrated_collection",
                        collection=collection_name,
                        count=len(documents),
                    )

            # Mark migration complete
            await self.tenant_db_service.update_tenant_status(
                tenant_id, TenantStatus.ACTIVE, "Migration completed successfully"
            )

            logger.info("tenant_migration_completed", tenant_id=tenant_id)
            return True

        except Exception as e:
            logger.error("tenant_migration_failed", tenant_id=tenant_id, error=str(e))
            await self.tenant_db_service.update_tenant_status(
                tenant_id, TenantStatus.ACTIVE, f"Migration failed: {str(e)}"
            )
            return False
