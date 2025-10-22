"""
Tenant Management API Router

REST API endpoints for tenant CRUD operations and management.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from structlog import get_logger

from .db_service import TenantDBService
from .models import TenantStatus
from .provisioning import TenantProvisioningService
from .schema import (
    TenantCreateRequest,
    TenantHealthCheckResponse,
    TenantListResponse,
    TenantProvisioningResponse,
    TenantResponse,
    TenantUpdateRequest,
)

logger = get_logger()

router = APIRouter(prefix="/platform/tenants", tags=["Tenant Management"])


def get_tenant_db_service() -> TenantDBService:
    """Dependency to get tenant database service."""
    return TenantDBService()


def get_provisioning_service() -> TenantProvisioningService:
    """Dependency to get provisioning service."""
    return TenantProvisioningService()


@router.post(
    "/",
    response_model=TenantProvisioningResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create new tenant",
    description="Provision a new tenant with complete database setup and configuration",
)
async def create_tenant(
    request: TenantCreateRequest,
    provisioning_service: TenantProvisioningService = Depends(get_provisioning_service),
) -> TenantProvisioningResponse:
    """
    Create and provision a new tenant.

    This endpoint:
    1. Validates subdomain availability
    2. Creates tenant record in platform database
    3. Provisions tenant-specific database
    4. Initializes schema and indexes
    5. Returns provisioning status
    """
    logger.info("creating_tenant", subdomain=request.subdomain, name=request.name)

    try:
        tenant = await provisioning_service.provision_tenant(request)

        return TenantProvisioningResponse(
            tenant_id=tenant.tenant_id,
            status=tenant.status,
            message="Tenant provisioned successfully",
            provisioning_steps=[
                {"step": "validate_subdomain", "status": "completed"},
                {"step": "create_tenant_record", "status": "completed"},
                {"step": "create_database", "status": "completed"},
                {"step": "initialize_schema", "status": "completed"},
                {"step": "activate_tenant", "status": "completed"},
            ],
            completed_steps=5,
            total_steps=5,
        )

    except ValueError as e:
        logger.error("tenant_creation_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("tenant_creation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create tenant",
        )


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Get tenant by ID",
    description="Retrieve tenant information by tenant ID",
)
async def get_tenant(
    tenant_id: str,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> TenantResponse:
    """Get tenant details by ID."""
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    return TenantResponse(**tenant.model_dump())


@router.get(
    "/",
    response_model=TenantListResponse,
    summary="List tenants",
    description="List all tenants with optional filtering and pagination",
)
async def list_tenants(
    status_filter: Optional[TenantStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> TenantListResponse:
    """List tenants with pagination and filtering."""
    skip = (page - 1) * page_size

    tenants = await tenant_service.list_tenants(
        status=status_filter,
        skip=skip,
        limit=page_size,
    )

    total = await tenant_service.count_tenants(status=status_filter)

    return TenantListResponse(
        tenants=[TenantResponse(**t.model_dump()) for t in tenants],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Update tenant",
    description="Update tenant configuration and settings",
)
async def update_tenant(
    tenant_id: str,
    request: TenantUpdateRequest,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> TenantResponse:
    """Update tenant configuration."""
    # Build update dictionary from non-None fields
    update_data = {}
    for field, value in request.model_dump(exclude_unset=True).items():
        if value is not None:
            # Handle nested config updates
            if field in ["branding", "domains", "features", "insurance", "compliance", "usage_limits"]:
                update_data[f"config.{field}"] = value
            else:
                update_data[field] = value

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    updated_tenant = await tenant_service.update_tenant(tenant_id, update_data)

    if not updated_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    logger.info("tenant_updated", tenant_id=tenant_id, fields=list(update_data.keys()))

    return TenantResponse(**updated_tenant.model_dump())


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate tenant",
    description="Deactivate a tenant (soft delete)",
)
async def deactivate_tenant(
    tenant_id: str,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
    provisioning_service: TenantProvisioningService = Depends(get_provisioning_service),
) -> None:
    """Deactivate a tenant."""
    success = await provisioning_service.deprovision_tenant(tenant_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    logger.info("tenant_deactivated", tenant_id=tenant_id)


@router.get(
    "/{tenant_id}/health",
    response_model=TenantHealthCheckResponse,
    summary="Tenant health check",
    description="Check tenant system health and connectivity",
)
async def tenant_health_check(
    tenant_id: str,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> TenantHealthCheckResponse:
    """Perform health check on tenant."""
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    # TODO: Implement actual health checks
    # For now, return basic status
    health_status = "healthy" if tenant.status == TenantStatus.ACTIVE else "unhealthy"

    return TenantHealthCheckResponse(
        tenant_id=tenant_id,
        status=health_status,
        database_connected=True,  # TODO: Actual DB connection check
        redis_connected=True,  # TODO: Actual Redis check
        agent_orchestrator_running=True,  # TODO: Actual orchestrator check
        last_agent_execution=tenant.last_activity_at,
        error_rate_last_hour=0.0,  # TODO: Calculate from audit logs
        average_response_time_ms=0.0,  # TODO: Calculate from metrics
        issues=[],
    )


@router.post(
    "/{tenant_id}/migrate",
    response_model=TenantProvisioningResponse,
    summary="Migrate tenant data",
    description="Migrate data from existing database to tenant database",
)
async def migrate_tenant_data(
    tenant_id: str,
    source_database: str,
    provisioning_service: TenantProvisioningService = Depends(get_provisioning_service),
) -> TenantProvisioningResponse:
    """Migrate data from source database to tenant database."""
    logger.info("starting_tenant_migration", tenant_id=tenant_id, source=source_database)

    success = await provisioning_service.migrate_tenant_data(tenant_id, source_database)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Migration failed",
        )

    return TenantProvisioningResponse(
        tenant_id=tenant_id,
        status=TenantStatus.ACTIVE,
        message="Migration completed successfully",
        provisioning_steps=[
            {"step": "data_migration", "status": "completed"},
        ],
        completed_steps=1,
        total_steps=1,
    )


@router.get(
    "/subdomain/{subdomain}",
    response_model=TenantResponse,
    summary="Get tenant by subdomain",
    description="Retrieve tenant information by subdomain",
)
async def get_tenant_by_subdomain(
    subdomain: str,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> TenantResponse:
    """Get tenant by subdomain."""
    tenant = await tenant_service.get_tenant_by_subdomain(subdomain)

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with subdomain '{subdomain}' not found",
        )

    return TenantResponse(**tenant.model_dump())


@router.get(
    "/check/subdomain/{subdomain}",
    response_model=dict,
    summary="Check subdomain availability",
    description="Check if a subdomain is available for registration",
)
async def check_subdomain_availability(
    subdomain: str,
    tenant_service: TenantDBService = Depends(get_tenant_db_service),
) -> dict:
    """Check if subdomain is available."""
    available = await tenant_service.subdomain_available(subdomain)

    return {
        "subdomain": subdomain,
        "available": available,
        "message": "Subdomain is available" if available else "Subdomain is already taken",
    }
