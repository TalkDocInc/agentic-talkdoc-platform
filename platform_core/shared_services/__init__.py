"""
Shared Services Module

Common services used across the platform including auth, database routing, and utilities.
"""

from .tenant_context import TenantContext, get_tenant_context

__all__ = ["TenantContext", "get_tenant_context"]
