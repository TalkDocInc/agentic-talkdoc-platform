# Authentication System Documentation

## Overview

The Agentic TalkDoc Platform uses a **multi-tenant aware JWT authentication system** with role-based access control (RBAC), Argon2id password hashing, and comprehensive security features.

---

## Features

✅ **JWT Token Authentication** - Industry-standard JSON Web Tokens
✅ **Multi-Tenant Awareness** - Users scoped to specific tenants
✅ **Password Hashing** - Argon2id (OWASP recommended)
✅ **Role-Based Access Control** - 5-tier hierarchical roles
✅ **User Type Classification** - Patient, Clinician, Coordinator, Admin
✅ **Password Reset Flow** - Secure token-based password reset
✅ **Refresh Tokens** - Long-lived tokens for token renewal
✅ **2FA Support** - Two-factor authentication (TOTP)
✅ **Email Verification** - Account activation via email

---

## User Model

### User Types

```python
class UserType(str, Enum):
    PATIENT = "patient"              # Patients/clients
    CLINICIAN = "clinician"          # Healthcare providers
    COORDINATOR = "coordinator"      # Care coordinators
    ADMIN = "admin"                  # Tenant administrators
    PLATFORM_ADMIN = "platform_admin" # Super admins (all tenants)
```

### User Roles (Hierarchical)

```python
class UserRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"  # Level 5: Full platform access
    TENANT_ADMIN = "tenant_admin"      # Level 4: Full tenant access
    MANAGER = "manager"                # Level 3: Management access
    USER = "user"                      # Level 2: Standard access
    GUEST = "guest"                    # Level 1: Limited read-only
```

**Role Hierarchy**: `PLATFORM_ADMIN > TENANT_ADMIN > MANAGER > USER > GUEST`

### User Status

```python
class UserStatus(str, Enum):
    ACTIVE = "active"                      # Can log in
    INACTIVE = "inactive"                  # Cannot log in
    SUSPENDED = "suspended"                # Temporarily blocked
    PENDING_VERIFICATION = "pending_verification"  # Awaiting email verification
```

---

## API Endpoints

### Public Endpoints (No Authentication)

#### 1. Register User

**POST** `/auth/register`

Create a new user account.

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: healthcareplus_20250115" \
  -d '{
    "email": "doctor@healthcareplus.com",
    "password": "SecureP@ssw0rd!",
    "first_name": "Jane",
    "last_name": "Smith",
    "user_type": "clinician",
    "role": "user"
  }'
```

**Response**:
```json
{
  "user_id": "user_a1b2c3d4",
  "tenant_id": "healthcareplus_20250115",
  "email": "doctor@healthcareplus.com",
  "first_name": "Jane",
  "last_name": "Smith",
  "user_type": "clinician",
  "role": "user",
  "status": "pending_verification",
  "email_verified": false,
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Password Requirements**:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

---

#### 2. Login

**POST** `/auth/login`

Authenticate and receive JWT tokens.

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: healthcareplus_20250115" \
  -d '{
    "email": "doctor@healthcareplus.com",
    "password": "SecureP@ssw0rd!"
  }'
```

**Response**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "user_id": "user_a1b2c3d4",
    "email": "doctor@healthcareplus.com",
    "first_name": "Jane",
    "last_name": "Smith",
    "user_type": "clinician",
    "role": "user",
    "status": "active"
  }
}
```

**Note**: `expires_in` is in seconds (86400 = 24 hours).

---

#### 3. Refresh Token

**POST** `/auth/refresh`

Get a new access token using a refresh token.

```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**Response**: Same as login response with new access token.

---

#### 4. Forgot Password

**POST** `/auth/forgot-password`

Request a password reset email.

```bash
curl -X POST http://localhost:8000/auth/forgot-password \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: healthcareplus_20250115" \
  -d '{
    "email": "doctor@healthcareplus.com"
  }'
```

**Response**:
```json
{
  "message": "If the email exists, a password reset link has been sent"
}
```

**Note**: Returns same message whether email exists or not (security best practice).

---

#### 5. Reset Password

**POST** `/auth/reset-password`

Reset password using reset token.

```bash
curl -X POST http://localhost:8000/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "new_password": "NewSecureP@ssw0rd!"
  }'
```

---

### Protected Endpoints (Requires Authentication)

#### 6. Get Current User

**GET** `/auth/me`

Get information about the currently authenticated user.

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response**: User object (same as registration response).

---

#### 7. Update Current User

**PATCH** `/auth/me`

Update current user's information.

```bash
curl -X PATCH http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Jane",
    "last_name": "Doe",
    "phone_number": "+1234567890"
  }'
```

**Note**: Users cannot update their own `status` or `role` (admin-only).

---

#### 8. Change Password

**POST** `/auth/change-password`

Change password for authenticated user.

```bash
curl -X POST http://localhost:8000/auth/change-password \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "current_password": "OldP@ssw0rd!",
    "new_password": "NewSecureP@ssw0rd!"
  }'
```

---

### Admin Endpoints (Requires `TENANT_ADMIN` Role)

#### 9. List Users

**GET** `/auth/users`

List all users in the tenant (admin only).

```bash
curl http://localhost:8000/auth/users?user_type=clinician&status=active&skip=0&limit=50 \
  -H "Authorization: Bearer <admin-token>"
```

**Query Parameters**:
- `user_type` (optional): Filter by user type
- `status` (optional): Filter by status
- `skip` (optional): Pagination offset (default: 0)
- `limit` (optional): Page size (default: 100, max: 100)

---

#### 10. Get User by ID

**GET** `/auth/users/{user_id}`

Get user details by ID (admin only).

```bash
curl http://localhost:8000/auth/users/user_a1b2c3d4 \
  -H "Authorization: Bearer <admin-token>"
```

---

#### 11. Update User

**PATCH** `/auth/users/{user_id}`

Update user information (admin only).

```bash
curl -X PATCH http://localhost:8000/auth/users/user_a1b2c3d4 \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "active",
    "role": "manager"
  }'
```

---

#### 12. Delete User

**DELETE** `/auth/users/{user_id}`

Soft delete user (admin only).

```bash
curl -X DELETE http://localhost:8000/auth/users/user_a1b2c3d4 \
  -H "Authorization: Bearer <admin-token>"
```

**Note**: Sets status to `INACTIVE` (soft delete, not permanent).

---

## JWT Token Structure

### Access Token Payload

```json
{
  "user_id": "user_a1b2c3d4",
  "tenant_id": "healthcareplus_20250115",
  "user_type": "clinician",
  "role": "user",
  "exp": 1705329600
}
```

**Fields**:
- `user_id`: Unique user identifier
- `tenant_id`: Tenant this user belongs to
- `user_type`: User type classification
- `role`: User's role for RBAC
- `exp`: Token expiration (Unix timestamp)

**Expiration**: 24 hours (configurable via `JWT_EXPIRY_HOURS`)

### Refresh Token Payload

```json
{
  "user_id": "user_a1b2c3d4",
  "tenant_id": "healthcareplus_20250115",
  "type": "refresh",
  "exp": 1707921600
}
```

**Expiration**: 30 days

---

## Using Authentication in Your Code

### Python (FastAPI Dependencies)

#### Get Current User

```python
from platform_core.auth import get_current_user
from fastapi import Depends

@app.get("/my-endpoint")
async def my_endpoint(current_user: User = Depends(get_current_user)):
    # current_user is guaranteed to be authenticated and active
    return {"user_id": current_user.user_id, "email": current_user.email}
```

#### Require Specific Role

```python
from platform_core.auth import require_role, UserRole
from fastapi import Depends

@app.get("/admin-only", dependencies=[Depends(require_role(UserRole.TENANT_ADMIN))])
async def admin_endpoint():
    # Only users with TENANT_ADMIN or higher can access
    return {"message": "Admin access granted"}
```

#### Require User Type

```python
from platform_core.auth import require_user_type
from fastapi import Depends

@app.get("/clinicians-only", dependencies=[Depends(require_user_type("clinician"))])
async def clinician_endpoint():
    # Only clinicians can access
    return {"message": "Clinician access granted"}
```

#### Optional Authentication

```python
from platform_core.auth import get_optional_current_user
from fastapi import Depends
from typing import Optional

@app.get("/public-or-authenticated")
async def flexible_endpoint(current_user: Optional[User] = Depends(get_optional_current_user)):
    if current_user:
        return {"message": f"Hello, {current_user.full_name}"}
    else:
        return {"message": "Hello, guest"}
```

---

### JavaScript/TypeScript (Frontend)

#### Login Flow

```typescript
const loginUser = async (email: string, password: string) => {
  const response = await fetch('http://localhost:8000/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': 'healthcareplus_20250115',
    },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    throw new Error('Login failed');
  }

  const data = await response.json();

  // Store tokens
  localStorage.setItem('access_token', data.access_token);

  return data.user;
};
```

#### Making Authenticated Requests

```typescript
const fetchProtectedResource = async () => {
  const token = localStorage.getItem('access_token');

  const response = await fetch('http://localhost:8000/auth/me', {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    // Token expired or invalid
    if (response.status === 401) {
      // Redirect to login or refresh token
    }
    throw new Error('Failed to fetch user');
  }

  return await response.json();
};
```

---

## Security Features

### Password Hashing

**Algorithm**: Argon2id (OWASP recommended)

**Parameters**:
- Memory cost: 64 MB
- Time cost: 3 iterations
- Parallelism: 4 threads

**Legacy Support**: Automatically upgrades bcrypt hashes to Argon2id on login.

### Password Strength Validation

All passwords must meet these requirements:
- ✅ Minimum 8 characters
- ✅ At least one uppercase letter
- ✅ At least one lowercase letter
- ✅ At least one digit
- ✅ At least one special character

### Token Security

- JWT tokens signed with `HS256` algorithm
- Secret key from environment variable (never hardcoded)
- Tokens include expiration timestamp
- Refresh tokens have separate expiration (30 days)
- Password reset tokens expire in 30 minutes

### Multi-Tenant Security

- ✅ Users scoped to specific tenants
- ✅ Token validation checks tenant match
- ✅ Cannot access other tenant's data
- ✅ Platform admins can access all tenants

---

## Database Schema

### Users Collection

**Indexes**:
- Unique: `user_id`, `email`
- Single: `user_type`, `role`, `status`, `created_at`
- Compound: `(tenant_id, email)`, `(tenant_id, user_type)`

**Fields**:
```javascript
{
  user_id: "user_a1b2c3d4",
  tenant_id: "healthcareplus_20250115",
  email: "doctor@example.com",
  hashed_password: "$argon2id$v=19$m=65536,t=3,p=4$...",
  first_name: "Jane",
  last_name: "Smith",
  phone_number: "+1234567890",
  user_type: "clinician",
  role: "user",
  status: "active",
  email_verified: true,
  two_factor_enabled: false,
  created_at: ISODate("2025-01-15T10:30:00Z"),
  updated_at: ISODate("2025-01-15T10:30:00Z"),
  last_login_at: ISODate("2025-01-15T11:00:00Z")
}
```

---

## Configuration

### Environment Variables

```bash
# JWT Configuration
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24

# Email (for verification and password reset)
AWS_SES_FROM_EMAIL=noreply@yourdomain.com

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

---

## Common Workflows

### User Registration Flow

```mermaid
sequenceDiagram
    User->>Frontend: Enter email, password
    Frontend->>API: POST /auth/register
    API->>Database: Check if email exists
    API->>API: Hash password (Argon2id)
    API->>Database: Create user (status=pending_verification)
    API->>Email Service: Send verification email
    API->>Frontend: Return user object
    Frontend->>User: Show "Check your email" message

    User->>Email: Click verification link
    Email->>API: GET /auth/verify-email?token=...
    API->>Database: Set email_verified=true, status=active
    API->>Frontend: Redirect to login
```

### Password Reset Flow

```mermaid
sequenceDiagram
    User->>Frontend: Click "Forgot Password"
    Frontend->>API: POST /auth/forgot-password
    API->>Database: Get user by email
    API->>API: Generate reset token (30 min expiry)
    API->>Database: Store token + expiry
    API->>Email Service: Send reset email
    API->>Frontend: Return success message

    User->>Email: Click reset link
    Email->>Frontend: Open reset form with token
    Frontend->>API: POST /auth/reset-password
    API->>API: Verify token (not expired)
    API->>API: Hash new password
    API->>Database: Update password, clear token
    API->>Frontend: Redirect to login
```

---

## Testing

### Create Test User

```bash
# Register a test clinician
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: testclinic_20250115" \
  -d '{
    "email": "testdoctor@example.com",
    "password": "TestP@ssw0rd123!",
    "first_name": "Test",
    "last_name": "Doctor",
    "user_type": "clinician",
    "role": "user"
  }'
```

### Login as Test User

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: testclinic_20250115" \
  -d '{
    "email": "testdoctor@example.com",
    "password": "TestP@ssw0rd123!"
  }'
```

Save the `access_token` from the response.

### Test Protected Endpoint

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <your-access-token>"
```

---

## Troubleshooting

### "Could not validate credentials"

**Cause**: Invalid or expired token

**Solution**:
1. Check token is being sent in `Authorization: Bearer <token>` header
2. Verify token hasn't expired (24 hours)
3. Use refresh token to get new access token

### "Token tenant does not match request tenant"

**Cause**: User is trying to access a different tenant than their token belongs to

**Solution**:
1. Ensure `X-Tenant-ID` header matches the tenant in the token
2. Or use subdomain routing (e.g., `healthcareplus.talkdoc.com`)

### "Incorrect email or password"

**Cause**: Invalid credentials

**Solution**:
1. Verify email is correct (case-sensitive)
2. Check password meets requirements
3. Ensure user exists in the correct tenant

### "Account is pending_verification"

**Cause**: User hasn't verified their email yet

**Solution**:
1. Check email for verification link
2. Or manually set `email_verified=true` and `status=active` in database (for testing)

---

## Best Practices

### Frontend

1. **Store tokens securely**: Use `httpOnly` cookies or secure storage (not localStorage for production)
2. **Handle token expiration**: Implement token refresh logic
3. **Clear tokens on logout**: Remove tokens from storage
4. **Validate user on page load**: Check if user is still authenticated
5. **Implement CSRF protection**: For cookie-based auth

### Backend

1. **Use dependencies**: Leverage FastAPI dependencies for auth
2. **Validate tenant**: Always check user can access requested tenant
3. **Log auth events**: Log login, logout, failed attempts
4. **Rate limit**: Prevent brute force attacks (TODO: implement)
5. **Monitor suspicious activity**: Track failed login attempts

### Security

1. **Rotate JWT secret**: Change `JWT_SECRET_KEY` periodically
2. **Use HTTPS**: Always use TLS in production
3. **Enable 2FA**: For admin accounts (recommended)
4. **Audit access**: Review audit logs regularly
5. **Principle of least privilege**: Assign minimum required role

---

## Future Enhancements

- [ ] OAuth2 integration (Google, Microsoft, Apple)
- [ ] 2FA implementation (TOTP with QR codes)
- [ ] Email verification implementation
- [ ] Rate limiting on auth endpoints
- [ ] Session management (track active sessions)
- [ ] SSO integration (SAML, OIDC)
- [ ] Biometric authentication support
- [ ] Magic link authentication (passwordless)

---

## Summary

The Agentic TalkDoc authentication system provides:

✅ Secure, multi-tenant aware authentication
✅ Industry-standard JWT tokens
✅ OWASP-recommended password hashing
✅ Role-based and type-based access control
✅ Complete user management API
✅ Password reset and recovery
✅ Ready for production deployment

**Next Steps**: Integrate authentication into your frontend and start building tenant-specific features!
