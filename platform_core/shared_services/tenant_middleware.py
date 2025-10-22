"""
Tenant Routing Middleware

FastAPI middleware that:
1. Identifies the tenant from request (subdomain, domain, or X-Tenant-ID header)
2. Loads tenant configuration
3. Establishes database connection to tenant-specific database
4. Sets tenant context for the request
"""

import re
from typing import Callable, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from structlog import get_logger

from ..config import get_config
from ..tenant_management.db_service import TenantDBService
from ..tenant_management.models import Tenant, TenantStatus
from .tenant_context import TenantContext, clear_tenant_context, set_tenant_context

config = get_config()
logger = get_logger()


class TenantRoutingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for multi-tenant request routing.

    Extracts tenant identifier, loads tenant config, and sets up database connection.
    """

    def __init__(
        self,
        app,
        mongo_client: Optional[AsyncIOMotorClient] = None,
        redis_client: Optional[aioredis.Redis] = None,
    ):
        """
        Initialize tenant routing middleware.

        Args:
            app: FastAPI application
            mongo_client: Optional MongoDB client (creates new if not provided)
            redis_client: Optional Redis client for caching
        """
        super().__init__(app)

        self.mongo_client = mongo_client or AsyncIOMotorClient(config.platform_mongo_db_url)
        self.redis_client = redis_client
        self.tenant_db_service = TenantDBService()

        # Compile regex for subdomain extraction
        self.subdomain_pattern = re.compile(r"^([a-z0-9-]+)\..*$", re.IGNORECASE)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and set tenant context.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/route handler

        Returns:
            HTTP response
        """
        # Skip tenant resolution for health checks and platform admin endpoints
        if self._is_platform_endpoint(request.url.path):
            return await call_next(request)

        try:
            # Step 1: Identify tenant
            tenant = await self._identify_tenant(request)

            if not tenant:
                logger.warning(
                    "tenant_not_found",
                    host=request.headers.get("host"),
                    path=request.url.path,
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Tenant not found. Please check your URL.",
                )

            # Step 2: Validate tenant status
            if tenant.status != TenantStatus.ACTIVE:
                logger.warning(
                    "tenant_not_active",
                    tenant_id=tenant.tenant_id,
                    status=tenant.status,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Service temporarily unavailable: {tenant.status_reason or 'Tenant is not active'}",
                )

            # Step 3: Establish database connection
            tenant_db = self.mongo_client[tenant.database_name]

            # Step 4: Create and set tenant context
            tenant_context = TenantContext(
                tenant=tenant,
                db=tenant_db,
                mongo_client=self.mongo_client,
            )
            set_tenant_context(tenant_context)

            # Add tenant info to request state for easy access
            request.state.tenant = tenant
            request.state.tenant_db = tenant_db

            logger.info(
                "tenant_context_set",
                tenant_id=tenant.tenant_id,
                database=tenant.database_name,
                path=request.url.path,
            )

            # Process request
            response = await call_next(request)

            # Add tenant identifier to response headers
            response.headers["X-Tenant-ID"] = tenant.tenant_id

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "tenant_middleware_error",
                error=str(e),
                host=request.headers.get("host"),
                path=request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing request",
            )
        finally:
            # Clean up context
            clear_tenant_context()

    async def _identify_tenant(self, request: Request) -> Optional[Tenant]:
        """
        Identify tenant from request.

        Tries in order:
        1. X-Tenant-ID header (for API clients)
        2. Subdomain from Host header
        3. Custom domain from Host header

        Args:
            request: HTTP request

        Returns:
            Tenant if identified, None otherwise
        """
        # Method 1: Check X-Tenant-ID header
        tenant_id_header = request.headers.get("X-Tenant-ID")
        if tenant_id_header:
            tenant = await self._get_tenant_cached(tenant_id_header, by="id")
            if tenant:
                return tenant

        # Method 2 & 3: Extract from Host header
        host = request.headers.get("host", "").split(":")[0]  # Remove port if present

        if not host:
            return None

        # Try subdomain first
        subdomain = self._extract_subdomain(host)
        if subdomain:
            tenant = await self._get_tenant_cached(subdomain, by="subdomain")
            if tenant:
                return tenant

        # Try full domain
        tenant = await self._get_tenant_cached(host, by="domain")
        if tenant:
            return tenant

        return None

    def _extract_subdomain(self, host: str) -> Optional[str]:
        """
        Extract subdomain from host.

        Args:
            host: Hostname

        Returns:
            Subdomain if found, None otherwise
        """
        # Skip localhost and IP addresses
        if host in ["localhost", "127.0.0.1"] or host.replace(".", "").isdigit():
            return None

        # Extract subdomain
        match = self.subdomain_pattern.match(host)
        if match:
            subdomain = match.group(1)
            # Ignore common subdomains
            if subdomain not in ["www", "api", "admin"]:
                return subdomain

        return None

    async def _get_tenant_cached(self, identifier: str, by: str) -> Optional[Tenant]:
        """
        Get tenant with caching support.

        Args:
            identifier: Tenant identifier (ID, subdomain, or domain)
            by: Lookup method ("id", "subdomain", or "domain")

        Returns:
            Tenant if found, None otherwise
        """
        cache_key = f"tenant:{by}:{identifier}"

        # Try cache first if Redis is available
        if self.redis_client:
            try:
                cached_data = await self.redis_client.get(cache_key)
                if cached_data:
                    tenant_dict = eval(cached_data)  # TODO: Use json.loads with proper serialization
                    return Tenant(**tenant_dict)
            except Exception as e:
                logger.warning("cache_read_error", key=cache_key, error=str(e))

        # Fetch from database
        if by == "id":
            tenant = await self.tenant_db_service.get_tenant_by_id(identifier)
        elif by == "subdomain":
            tenant = await self.tenant_db_service.get_tenant_by_subdomain(identifier)
        elif by == "domain":
            tenant = await self.tenant_db_service.get_tenant_by_domain(identifier)
        else:
            return None

        # Cache if found
        if tenant and self.redis_client:
            try:
                # Cache for 5 minutes
                await self.redis_client.setex(
                    cache_key,
                    300,
                    str(tenant.model_dump()),
                )
            except Exception as e:
                logger.warning("cache_write_error", key=cache_key, error=str(e))

        return tenant

    def _is_platform_endpoint(self, path: str) -> bool:
        """
        Check if path is a platform-level endpoint (no tenant context needed).

        Args:
            path: Request path

        Returns:
            True if platform endpoint
        """
        platform_prefixes = [
            "/health",
            "/ping",
            "/platform/",
            "/admin/tenants",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]

        return any(path.startswith(prefix) for prefix in platform_prefixes)
