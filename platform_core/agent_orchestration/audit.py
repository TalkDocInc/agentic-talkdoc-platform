"""
Agent Audit Logging

Comprehensive audit trail for all agent executions with HIPAA compliance.
"""

from datetime import datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel


class AgentAuditLog(BaseModel):
    """
    Agent execution audit log entry.

    Stored in tenant-specific database for compliance and traceability.
    """

    log_id: str = Field(..., description="Unique log identifier (same as execution_id)")
    tenant_id: str = Field(..., description="Tenant identifier")

    # Agent information
    agent_type: str
    agent_version: str
    status: str  # success, failed, timeout, etc.

    # Execution data
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0)

    # Metrics
    execution_time_ms: float
    error: Optional[str] = Field(default=None)
    error_details: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = Field(default=0)
    api_calls_made: int = Field(default=0)
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)

    # Review flags
    needs_human_review: bool = Field(default=False)
    review_reason: Optional[str] = Field(default=None)
    reviewed_by: Optional[str] = Field(default=None)
    reviewed_at: Optional[datetime] = Field(default=None)
    review_notes: Optional[str] = Field(default=None)

    # User and context
    user_id: Optional[str] = Field(default=None, description="User who triggered the agent")
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    context: dict[str, Any] = Field(default_factory=dict)

    # Compliance
    phi_accessed: bool = Field(default=False, description="Whether PHI was accessed")
    phi_modified: bool = Field(default=False, description="Whether PHI was modified")
    compliance_tags: list[str] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "log_id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "talkdoc_prod",
                "agent_type": "insurance_verification",
                "agent_version": "1.0.0",
                "status": "success",
                "confidence": 0.95,
                "execution_time_ms": 1234.5,
                "needs_human_review": False,
            }
        }


class AgentAuditService:
    """Service for managing agent audit logs."""

    def __init__(self):
        """Initialize audit service."""
        self.collection_name = "agent_audit_logs"

    async def ensure_indexes(self, db: AsyncIOMotorDatabase) -> None:
        """
        Create indexes for audit log collection.

        Args:
            db: Tenant database
        """
        collection = db[self.collection_name]

        indexes = [
            IndexModel([("log_id", ASCENDING)], unique=True),
            IndexModel([("agent_type", ASCENDING)]),
            IndexModel([("executed_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("needs_human_review", ASCENDING)]),
            IndexModel([("reviewed_by", ASCENDING)]),
            # Compound index for common queries
            IndexModel([("agent_type", ASCENDING), ("executed_at", DESCENDING)]),
            IndexModel([("status", ASCENDING), ("executed_at", DESCENDING)]),
        ]

        await collection.create_indexes(indexes)

    async def create_log(self, audit_log: AgentAuditLog, db: AsyncIOMotorDatabase) -> str:
        """
        Create audit log entry.

        Args:
            audit_log: Audit log data
            db: Tenant database

        Returns:
            Log ID
        """
        collection = db[self.collection_name]
        log_dict = audit_log.model_dump()

        await collection.insert_one(log_dict)

        return audit_log.log_id

    async def get_log(self, log_id: str, db: AsyncIOMotorDatabase) -> Optional[AgentAuditLog]:
        """
        Get audit log by ID.

        Args:
            log_id: Log identifier
            db: Tenant database

        Returns:
            Audit log if found
        """
        collection = db[self.collection_name]
        log_dict = await collection.find_one({"log_id": log_id})

        if log_dict:
            return AgentAuditLog(**log_dict)
        return None

    async def list_logs(
        self,
        db: AsyncIOMotorDatabase,
        agent_type: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        needs_review: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentAuditLog]:
        """
        List audit logs with filtering.

        Args:
            db: Tenant database
            agent_type: Filter by agent type
            user_id: Filter by user
            status: Filter by status
            needs_review: Filter by review flag
            start_date: Filter by start date
            end_date: Filter by end date
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            List of audit logs
        """
        collection = db[self.collection_name]

        query: dict[str, Any] = {}

        if agent_type:
            query["agent_type"] = agent_type
        if user_id:
            query["user_id"] = user_id
        if status:
            query["status"] = status
        if needs_review is not None:
            query["needs_human_review"] = needs_review

        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["executed_at"] = date_query

        cursor = collection.find(query).sort("executed_at", DESCENDING).skip(skip).limit(limit)

        logs = []
        async for log_dict in cursor:
            logs.append(AgentAuditLog(**log_dict))

        return logs

    async def mark_reviewed(
        self,
        log_id: str,
        reviewed_by: str,
        review_notes: Optional[str],
        db: AsyncIOMotorDatabase,
    ) -> bool:
        """
        Mark audit log as reviewed.

        Args:
            log_id: Log identifier
            reviewed_by: User ID who reviewed
            review_notes: Optional review notes
            db: Tenant database

        Returns:
            True if updated
        """
        collection = db[self.collection_name]

        result = await collection.update_one(
            {"log_id": log_id},
            {
                "$set": {
                    "reviewed_by": reviewed_by,
                    "reviewed_at": datetime.utcnow(),
                    "review_notes": review_notes,
                    "needs_human_review": False,
                }
            },
        )

        return result.modified_count > 0

    async def get_agent_stats(
        self,
        db: AsyncIOMotorDatabase,
        agent_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        Get agent execution statistics.

        Args:
            db: Tenant database
            agent_type: Optional agent type filter
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            Statistics dictionary
        """
        collection = db[self.collection_name]

        match_stage: dict[str, Any] = {}
        if agent_type:
            match_stage["agent_type"] = agent_type
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            match_stage["executed_at"] = date_query

        pipeline = []
        if match_stage:
            pipeline.append({"$match": match_stage})

        pipeline.extend(
            [
                {
                    "$group": {
                        "_id": None,
                        "total_executions": {"$sum": 1},
                        "successful_executions": {
                            "$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}
                        },
                        "failed_executions": {
                            "$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}
                        },
                        "avg_execution_time_ms": {"$avg": "$execution_time_ms"},
                        "avg_confidence": {"$avg": "$confidence"},
                        "total_cost_usd": {"$sum": "$cost_usd"},
                        "total_tokens_used": {"$sum": "$tokens_used"},
                        "needs_review_count": {
                            "$sum": {"$cond": ["$needs_human_review", 1, 0]}
                        },
                    }
                }
            ]
        )

        result = await collection.aggregate(pipeline).to_list(length=1)

        if result:
            stats = result[0]
            stats.pop("_id", None)
            # Calculate success rate
            total = stats.get("total_executions", 0)
            success = stats.get("successful_executions", 0)
            stats["success_rate"] = (success / total * 100) if total > 0 else 0.0
            return stats

        return {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "success_rate": 0.0,
            "avg_execution_time_ms": 0.0,
            "avg_confidence": 0.0,
            "total_cost_usd": 0.0,
            "total_tokens_used": 0,
            "needs_review_count": 0,
        }

    async def count_logs(
        self,
        db: AsyncIOMotorDatabase,
        agent_type: Optional[str] = None,
        status: Optional[str] = None,
        needs_review: Optional[bool] = None,
    ) -> int:
        """
        Count audit logs.

        Args:
            db: Tenant database
            agent_type: Optional agent type filter
            status: Optional status filter
            needs_review: Optional review flag filter

        Returns:
            Number of logs
        """
        collection = db[self.collection_name]

        query: dict[str, Any] = {}
        if agent_type:
            query["agent_type"] = agent_type
        if status:
            query["status"] = status
        if needs_review is not None:
            query["needs_human_review"] = needs_review

        return await collection.count_documents(query)
