"""
User Database Service

CRUD operations for users in tenant databases.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from .models import User, UserCreate, UserRole, UserStatus, UserType
from .security import get_password_hash


class UserDBService:
    """
    Database service for user management.

    Operates on tenant-specific databases.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize user database service.

        Args:
            db: Tenant database instance
        """
        self.db = db
        self.collection = db["users"]

    async def ensure_indexes(self) -> None:
        """Create necessary indexes for user collection."""
        indexes = [
            IndexModel([("user_id", ASCENDING)], unique=True),
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("user_type", ASCENDING)]),
            IndexModel([("role", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)]),
            # Compound index for common queries
            IndexModel([("tenant_id", ASCENDING), ("email", ASCENDING)]),
            IndexModel([("tenant_id", ASCENDING), ("user_type", ASCENDING)]),
        ]
        await self.collection.create_indexes(indexes)

    async def create_user(
        self,
        user_create: UserCreate,
        tenant_id: str,
        created_by: Optional[str] = None,
    ) -> User:
        """
        Create a new user.

        Args:
            user_create: User creation data
            tenant_id: Tenant ID for this user
            created_by: User ID who created this user

        Returns:
            Created user

        Raises:
            ValueError: If email already exists
        """
        # Generate user ID
        user_id = f"user_{str(uuid4())[:8]}"

        # Hash password
        hashed_password = get_password_hash(user_create.password)

        # Create user object
        user = User(
            user_id=user_id,
            tenant_id=tenant_id,
            email=user_create.email,
            hashed_password=hashed_password,
            first_name=user_create.first_name,
            last_name=user_create.last_name,
            phone_number=user_create.phone_number,
            user_type=user_create.user_type,
            role=user_create.role,
            status=UserStatus.PENDING_VERIFICATION,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by=created_by,
        )

        user_dict = user.model_dump()

        try:
            await self.collection.insert_one(user_dict)
            return user
        except DuplicateKeyError:
            raise ValueError(f"User with email '{user_create.email}' already exists")

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User identifier

        Returns:
            User if found, None otherwise
        """
        user_dict = await self.collection.find_one({"user_id": user_id})
        if user_dict:
            return User(**user_dict)
        return None

    async def get_user_by_email(self, email: str, tenant_id: str) -> Optional[User]:
        """
        Get user by email within a tenant.

        Args:
            email: User email
            tenant_id: Tenant identifier

        Returns:
            User if found, None otherwise
        """
        user_dict = await self.collection.find_one({"email": email, "tenant_id": tenant_id})
        if user_dict:
            return User(**user_dict)
        return None

    async def update_user(
        self,
        user_id: str,
        update_data: dict,
        updated_by: Optional[str] = None,
    ) -> Optional[User]:
        """
        Update user information.

        Args:
            user_id: User identifier
            update_data: Fields to update
            updated_by: User ID performing the update

        Returns:
            Updated user if found, None otherwise
        """
        update_data["updated_at"] = datetime.utcnow()
        if updated_by:
            update_data["updated_by"] = updated_by

        result = await self.collection.find_one_and_update(
            {"user_id": user_id},
            {"$set": update_data},
            return_document=True,
        )

        if result:
            return User(**result)
        return None

    async def update_password(self, user_id: str, new_password: str) -> bool:
        """
        Update user password.

        Args:
            user_id: User identifier
            new_password: New plain text password

        Returns:
            True if updated, False if user not found
        """
        hashed_password = get_password_hash(new_password)

        result = await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "hashed_password": hashed_password,
                    "updated_at": datetime.utcnow(),
                    "password_reset_token": None,
                    "password_reset_expires": None,
                }
            },
        )

        return result.modified_count > 0

    async def update_last_login(self, user_id: str) -> bool:
        """
        Update user's last login timestamp.

        Args:
            user_id: User identifier

        Returns:
            True if updated, False if user not found
        """
        result = await self.collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_login_at": datetime.utcnow()}},
        )

        return result.modified_count > 0

    async def verify_email(self, user_id: str) -> bool:
        """
        Mark user email as verified and activate account.

        Args:
            user_id: User identifier

        Returns:
            True if updated, False if user not found
        """
        result = await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "email_verified": True,
                    "status": UserStatus.ACTIVE,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.modified_count > 0

    async def set_password_reset_token(
        self,
        user_id: str,
        token: str,
        expires: datetime,
    ) -> bool:
        """
        Set password reset token for user.

        Args:
            user_id: User identifier
            token: Reset token
            expires: Token expiration time

        Returns:
            True if updated, False if user not found
        """
        result = await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "password_reset_token": token,
                    "password_reset_expires": expires,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.modified_count > 0

    async def list_users(
        self,
        tenant_id: str,
        user_type: Optional[UserType] = None,
        status: Optional[UserStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        """
        List users with filtering.

        Args:
            tenant_id: Tenant identifier
            user_type: Filter by user type
            status: Filter by status
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            List of users
        """
        query = {"tenant_id": tenant_id}

        if user_type:
            query["user_type"] = user_type
        if status:
            query["status"] = status

        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)

        users = []
        async for user_dict in cursor:
            users.append(User(**user_dict))

        return users

    async def count_users(
        self,
        tenant_id: str,
        user_type: Optional[UserType] = None,
        status: Optional[UserStatus] = None,
    ) -> int:
        """
        Count users.

        Args:
            tenant_id: Tenant identifier
            user_type: Optional user type filter
            status: Optional status filter

        Returns:
            Number of users matching criteria
        """
        query = {"tenant_id": tenant_id}

        if user_type:
            query["user_type"] = user_type
        if status:
            query["status"] = status

        return await self.collection.count_documents(query)

    async def delete_user(self, user_id: str) -> bool:
        """
        Soft delete user (set status to INACTIVE).

        Args:
            user_id: User identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "status": UserStatus.INACTIVE,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        return result.modified_count > 0

    async def hard_delete_user(self, user_id: str) -> bool:
        """
        Permanently delete user.

        WARNING: This is irreversible.

        Args:
            user_id: User identifier

        Returns:
            True if deleted, False if not found
        """
        result = await self.collection.delete_one({"user_id": user_id})
        return result.deleted_count > 0

    async def user_exists(self, email: str, tenant_id: str) -> bool:
        """
        Check if user with email exists in tenant.

        Args:
            email: User email
            tenant_id: Tenant identifier

        Returns:
            True if exists, False otherwise
        """
        count = await self.collection.count_documents(
            {"email": email, "tenant_id": tenant_id}, limit=1
        )
        return count > 0

    async def update_role(self, user_id: str, role: UserRole) -> bool:
        """
        Update user's role.

        Args:
            user_id: User identifier
            role: New role

        Returns:
            True if updated, False if user not found
        """
        result = await self.collection.update_one(
            {"user_id": user_id},
            {"$set": {"role": role, "updated_at": datetime.utcnow()}},
        )

        return result.modified_count > 0
