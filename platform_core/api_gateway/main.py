"""
Main FastAPI Application

Agentic TalkDoc Platform API Gateway with:
- Multi-tenant routing
- Agent orchestration endpoints
- Platform management
- CORS configuration
- Health checks
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from structlog import get_logger

from ..config import get_config
from ..shared_services.tenant_middleware import TenantRoutingMiddleware
from ..tenant_management.api_router import router as tenant_router
from ..tenant_management.db_service import TenantDBService

config = get_config()
logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info("starting_agentic_talkdoc_platform", environment=config.environment.value)

    # Initialize MongoDB connection
    app.state.mongo_client = AsyncIOMotorClient(config.platform_mongo_db_url)
    app.state.platform_db = app.state.mongo_client[config.platform_mongo_db_name]

    # Ensure platform database indexes
    tenant_service = TenantDBService(app.state.platform_db)
    await tenant_service.ensure_indexes()

    logger.info("platform_initialized")

    yield

    # Shutdown
    logger.info("shutting_down_platform")
    app.state.mongo_client.close()
    logger.info("platform_shutdown_complete")


# Create FastAPI application
app = FastAPI(
    title="Agentic TalkDoc Platform",
    description="Specialty-agnostic, multi-tenant agentic healthcare platform with AI agent orchestration",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not config.is_production else None,
    redoc_url="/redoc" if not config.is_production else None,
    openapi_url="/openapi.json" if not config.is_production else None,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add tenant routing middleware
app.add_middleware(TenantRoutingMiddleware)


# Health check endpoints
@app.get("/health", tags=["Platform"], summary="Health check")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "environment": config.environment.value,
        "version": "0.1.0",
    }


@app.get("/ping", tags=["Platform"], summary="Ping endpoint")
async def ping():
    """Simple ping endpoint."""
    return {"message": "pong"}


@app.get("/", tags=["Platform"], summary="Root endpoint")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic TalkDoc Platform",
        "version": "0.1.0",
        "description": "Multi-tenant agentic healthcare platform",
        "environment": config.environment.value,
        "docs_url": "/docs" if not config.is_production else None,
    }


# Platform status endpoint
@app.get("/platform/status", tags=["Platform"], summary="Platform status")
async def platform_status(request: Request):
    """Get platform status and statistics."""
    tenant_service = TenantDBService(request.app.state.platform_db)

    total_tenants = await tenant_service.count_tenants()
    active_tenants = await tenant_service.count_tenants(status="active")

    return {
        "status": "operational",
        "environment": config.environment.value,
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "features": {
            "agent_execution": config.enable_agent_execution,
            "multi_agent_workflows": config.enable_multi_agent_workflows,
            "realtime_monitoring": config.enable_realtime_monitoring,
        },
    }


# Exception handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "Resource not found", "path": str(request.url.path)},
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """Custom 500 handler."""
    logger.error("internal_server_error", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# Include routers
app.include_router(tenant_router)

# Authentication router
from ..auth.api_router import router as auth_router
app.include_router(auth_router)

# Agent execution router
from ..agent_execution.api_router import router as agent_router
app.include_router(agent_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if config.environment == "local" else False,
        log_level=config.log_level.lower(),
    )
