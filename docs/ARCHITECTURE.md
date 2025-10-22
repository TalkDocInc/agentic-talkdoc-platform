---
# Agentic TalkDoc Platform - Architecture Documentation

## Overview

The Agentic TalkDoc Platform is a **specialty-agnostic, multi-tenant healthcare platform** that uses AI agents to automate billing, care coordination, and patient engagement. This document describes the platform's architecture, design decisions, and key components.

---

## Architecture Principles

### 1. Multi-Tenancy with Database-per-Tenant

**Decision**: Each tenant (white-label customer) gets their own dedicated MongoDB database.

**Rationale**:
- **Maximum data isolation**: Complete separation of PHI/PII between tenants
- **HIPAA compliance**: Easier to prove data segregation for audits
- **Tenant-specific backups**: Independent backup/restore per tenant
- **Performance isolation**: One tenant's load doesn't affect others
- **Easier migration**: Can move individual tenant databases

**Trade-offs**:
- Higher infrastructure complexity than shared database
- More database connections to manage
- Slightly higher MongoDB hosting costs

**Implementation**:
- Platform database: Stores tenant metadata, configurations, usage metrics
- Tenant databases: Format `talkdoc_tenant_{tenant_id}`, stores all PHI/operational data
- Middleware: `TenantRoutingMiddleware` routes requests to correct database

### 2. Fully Autonomous Agents with Audit Trails

**Decision**: Agents execute autonomously without pre-approval, with comprehensive audit logging.

**Rationale**:
- **Efficiency**: 40% reduction in administrative tasks (per market research)
- **Scalability**: Agents can handle high volume without human bottlenecks
- **Consistency**: Agents apply rules consistently every time
- **Compliance**: Full audit trail for every agent action

**Trade-offs**:
- Requires high confidence thresholds (85%+)
- Must flag low-confidence actions for review
- Needs robust error handling and rollback

**Implementation**:
- `BaseAgent`: Abstract class with standardized execution interface
- `AgentAuditLog`: HIPAA-compliant audit trail in tenant database
- Confidence scoring: Every agent returns 0.0-1.0 confidence score
- Review flags: Low-confidence actions marked for human review

### 3. Specialty-Agnostic Core

**Decision**: Platform is configurable for any healthcare specialty, not hardcoded for mental health.

**Rationale**:
- **Market expansion**: Can serve mental health, primary care, cardiology, etc.
- **White-labeling**: Easier to customize per customer
- **Reusability**: Core features work across specialties

**Implementation**:
- `SpecialtyType` enum: Defines supported specialties
- Tenant configuration: Each tenant specifies enabled specialties
- Dynamic forms: Intake forms, assessments vary by specialty
- Agent configuration: Specialty-specific agents enabled per tenant

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │Patient Portal│  │Clinician     │  │Admin Console │          │
│  │ (React/Vite) │  │Dashboard     │  │  (React)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      API Gateway Layer                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ FastAPI Application (Uvicorn)                              │ │
│  │ • CORS Middleware                                          │ │
│  │ • Tenant Routing Middleware  ← Identifies tenant          │ │
│  │ • Authentication Middleware  ← Validates JWT              │ │
│  │ • Rate Limiting Middleware   ← Prevents abuse             │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   Platform Core Services                         │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │Tenant Management │  │Agent Orchestrator│                    │
│  │ • Provisioning   │  │ • Task Queue     │                    │
│  │ • Configuration  │  │ • Workflow Engine│                    │
│  │ • Health Checks  │  │ • Agent Registry │                    │
│  └──────────────────┘  └──────────────────┘                    │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │Shared Services   │  │Auth & Security   │                    │
│  │ • Video (Chime)  │  │ • JWT Tokens     │                    │
│  │ • Email (SES)    │  │ • Password Hash  │                    │
│  │ • SMS            │  │ • 2FA            │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Layer                               │
│  ┌──────────────────┐  ┌──────────────────┐ ┌────────────────┐ │
│  │Revenue Cycle (5) │  │Care Coord (5)    │ │Patient Eng (5) │ │
│  │ • Insurance      │  │ • Intake         │ │ • AI Advisor   │ │
│  │ • Coding         │  │ • Scheduling     │ │ • Appointment  │ │
│  │ • Claims         │  │ • Follow-up      │ │ • Education    │ │
│  │ • Denial Predict │  │ • Cross-Provider │ │ • Assessment   │ │
│  │ • Appeals        │  │ • Care Plans     │ │ • Outcomes     │ │
│  └──────────────────┘  └──────────────────┘ └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Data & Integration Layer                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │Platform DB  │  │Tenant DBs   │  │Redis Cache  │            │
│  │• Tenant     │  │• Users      │  │• Sessions   │            │
│  │  Metadata   │  │• Appts      │  │• Tenant     │            │
│  │• Usage Stats│  │• Audit Logs │  │  Configs    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │Stedi EDI    │  │AWS Chime    │  │OpenAI/      │            │
│  │(Insurance)  │  │(Video)      │  │Anthropic    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Tenant Management System

**Location**: `platform_core/tenant_management/`

**Responsibilities**:
- Tenant provisioning and deprovisioning
- Configuration management
- Database creation and initialization
- Health monitoring

**Key Files**:
- `models.py`: Tenant data models, status, configurations
- `schema.py`: API request/response schemas
- `db_service.py`: CRUD operations on platform database
- `provisioning.py`: Automated tenant provisioning workflow
- `api_router.py`: REST endpoints for tenant management

**Workflow - Creating a Tenant**:
```
1. API Request → TenantCreateRequest
2. Validate subdomain availability
3. Generate tenant_id (subdomain + timestamp)
4. Create tenant record in platform DB
5. Create tenant-specific MongoDB database
6. Initialize collections and indexes
7. Set status to ACTIVE
8. Return TenantProvisioningResponse
```

### 2. Tenant Routing Middleware

**Location**: `platform_core/shared_services/tenant_middleware.py`

**Responsibilities**:
- Identify tenant from request (subdomain, domain, or X-Tenant-ID header)
- Load tenant configuration from platform database
- Establish connection to tenant-specific database
- Set tenant context for the request

**Request Flow**:
```
1. Request arrives at API gateway
2. Middleware extracts tenant identifier:
   - Check X-Tenant-ID header
   - Extract subdomain from Host header
   - Check full domain
3. Load tenant from platform DB (with Redis caching)
4. Validate tenant status == ACTIVE
5. Get tenant-specific database connection
6. Set TenantContext in context variable
7. Add tenant info to request.state
8. Continue to route handler
9. Clean up context after request
```

**Context Variable**:
Uses Python's `contextvars` for request-scoped tenant context:
```python
tenant_context = get_tenant_context()
tenant_db = tenant_context.db
tenant_config = tenant_context.config
```

### 3. Base Agent Framework

**Location**: `platform_core/agent_orchestration/base_agent.py`

**Responsibilities**:
- Standardized agent execution interface
- Retry logic with exponential backoff
- Comprehensive audit logging
- Error handling and timeout management
- Confidence scoring and review flagging

**Agent Lifecycle**:
```
1. execute() called with input_data
2. Generate execution_id (UUID)
3. Check tenant has agent enabled
4. Execute with retry logic:
   - Call _execute_internal() (implemented by subclass)
   - Retry up to max_retries on failure
   - Exponential backoff between retries
5. Calculate confidence score
6. Flag for review if confidence < threshold
7. Log to audit trail in tenant database
8. Increment tenant agent action count
9. Return AgentResult
```

**Agent Result Structure**:
```python
AgentResult(
    execution_id="uuid",
    agent_type="insurance_verification",
    status=AgentStatus.SUCCESS,
    output=OutputType(...),
    confidence=0.95,
    execution_time_ms=1234.5,
    needs_human_review=False,
    user_id="user123",
    tenant_id="tenant_abc",
    context={...}
)
```

### 4. Audit Logging System

**Location**: `platform_core/agent_orchestration/audit.py`

**Responsibilities**:
- Store all agent executions in tenant database
- Support filtering and querying audit logs
- Calculate agent statistics
- Mark logs as reviewed

**Audit Log Schema**:
```python
{
    "log_id": "execution_id",
    "tenant_id": "tenant_abc",
    "agent_type": "insurance_verification",
    "agent_version": "1.0.0",
    "status": "success",
    "input_data": {...},
    "output_data": {...},
    "confidence": 0.95,
    "execution_time_ms": 1234.5,
    "needs_human_review": False,
    "executed_at": "2025-01-15T10:30:00Z",
    "user_id": "user123",
    "phi_accessed": True,
    "phi_modified": False,
    "compliance_tags": ["HIPAA"]
}
```

**Indexes**:
- Unique: `log_id`
- Single: `agent_type`, `executed_at`, `user_id`, `status`
- Compound: `(agent_type, executed_at)`, `(status, executed_at)`

---

## Database Design

### Platform Database (`agentic_talkdoc_platform`)

**Collections**:
1. **tenants**: Tenant records and configurations
   - Unique indexes: `tenant_id`, `subdomain`, `primary_domain`
   - Regular indexes: `status`, `created_at`

### Tenant Databases (`talkdoc_tenant_{tenant_id}`)

**Collections** (initialized during provisioning):
1. **users**: Patient, clinician, coordinator accounts
2. **appointments**: Appointment records
3. **availabilities**: Clinician availability schedules
4. **chime_meetings**: Video meeting records
5. **agent_audit_logs**: Agent execution audit trail ⭐
6. **agent_tasks**: Scheduled/queued agent tasks

---

## Multi-Tenant Routing

### Subdomain-Based Routing

**Example**: `https://healthcareplus.platform.talkdoc.com/api/appointments`

```
1. Extract subdomain: "healthcareplus"
2. Query platform DB: tenants WHERE subdomain = "healthcareplus"
3. Get tenant_id: "healthcareplus_20250115"
4. Connect to: talkdoc_tenant_healthcareplus_20250115
5. Route request to tenant-specific handler
```

### Custom Domain Routing

**Example**: `https://www.healthcareplus.com/api/appointments`

```
1. Extract domain: "healthcareplus.com"
2. Query platform DB: tenants WHERE primary_domain = "healthcareplus.com"
3. Get tenant_id: "healthcareplus_20250115"
4. Continue as above
```

### Header-Based Routing (API Clients)

**Example**: `curl -H "X-Tenant-ID: healthcareplus_20250115" https://api.talkdoc.com/appointments`

```
1. Read X-Tenant-ID header
2. Query platform DB: tenants WHERE tenant_id = "healthcareplus_20250115"
3. Connect and route
```

---

## Agent Architecture

### Agent Interface

All agents implement:
```python
class MyAgent(BaseAgent[InputType, OutputType]):
    async def _execute_internal(
        self,
        input_data: InputType,
        context: dict[str, Any]
    ) -> tuple[OutputType, float, dict[str, Any]]:
        # 1. Perform agent-specific logic
        # 2. Call external APIs if needed
        # 3. Return (output, confidence, metrics)
        pass
```

### Insurance Verification Agent (POC)

**Flow**:
```
1. Receive patient demographics + insurance info
2. Get Stedi API key from tenant config
3. Build EDI 270 (Eligibility Inquiry) request
4. Call Stedi API
5. Parse EDI 271 (Eligibility Response)
6. Extract coverage details:
   - Active status
   - Copay, deductible, OOP max
   - Prior auth requirements
   - Network status
7. Calculate confidence:
   - Base: 0.5
   - +0.3 if verified
   - +0.1 if detailed coverage
   - -0.1 per issue
8. Return verification output
```

**Confidence Calculation**:
```python
confidence = 0.5
if verified: confidence += 0.3
if has_coverage_details: confidence += 0.1
if has_copay_info: confidence += 0.05
if has_deductible_info: confidence += 0.05
if has_issues: confidence -= 0.1 * len(issues)
return max(0.0, min(1.0, confidence))
```

---

## Security & Compliance

### HIPAA Compliance

1. **Data Encryption**:
   - At rest: MongoDB encrypted storage
   - In transit: TLS 1.3 for all API calls
   - Backups: Encrypted backups per tenant

2. **Access Controls**:
   - Role-based access (RBAC) per tenant
   - MFA for admin accounts
   - Audit logging for all PHI access

3. **Audit Trail**:
   - Every agent execution logged
   - Immutable audit logs (append-only)
   - 7-year retention default

4. **Data Isolation**:
   - Database-per-tenant architecture
   - No cross-tenant queries possible
   - Tenant context validated on every request

### JWT Authentication

**Token Structure**:
```json
{
    "user_id": "user_123",
    "tenant_id": "healthcareplus_20250115",
    "user_type": "clinician",
    "exp": 1705329600
}
```

**Validation**:
- Verify signature with JWT_SECRET_KEY
- Check expiration
- Validate tenant_id matches request tenant
- Check user has required role

---

## Deployment Architecture

### Local Development
```
Docker Compose:
- MongoDB (port 27017)
- Redis (port 6379)
- FastAPI Backend (port 8000)
- React Admin Console (port 3000)
```

### AWS Production
```
- API Gateway: AWS Lambda (FastAPI via Mangum)
- Databases: MongoDB Atlas (multi-region)
- Caching: ElastiCache Redis
- Video: AWS Chime SDK
- Email: AWS SES
- Task Queue: AWS SQS + Step Functions
- Monitoring: CloudWatch
```

---

## Performance Considerations

### Caching Strategy

**Redis Cache**:
- Tenant configurations (5-minute TTL)
- User sessions (24-hour TTL)
- Frequently accessed data

**Cache Keys**:
```
tenant:id:{tenant_id}
tenant:subdomain:{subdomain}
tenant:domain:{domain}
user:session:{session_id}
```

### Database Connection Pooling

- Platform DB: Persistent connection pool
- Tenant DBs: Connection pooling with max 100 connections
- Lazy loading: Connect to tenant DB only when needed
- Connection reuse: Same request reuses connection

### Rate Limiting

- Per-tenant rate limits from configuration
- Default: 100 req/min, 1000 req/hour
- Implemented via middleware
- Returns 429 Too Many Requests when exceeded

---

## Future Enhancements

1. **Task Queue System** (Pending):
   - AWS SQS for async agent tasks
   - Scheduled agents (e.g., daily eligibility checks)
   - Multi-agent workflows (chain agents together)

2. **Authentication System** (Pending):
   - Multi-tenant aware auth
   - OAuth2/OIDC support
   - SSO integration

3. **Remaining Agents** (Pending):
   - 14 more agents to implement
   - Medical coding agent (NLP)
   - Claims generation agent
   - Smart scheduling agent
   - AI health advisor (extended chat)

4. **Observability**:
   - DataDog integration
   - Real-time agent monitoring dashboard
   - Alerting for failed agents
   - Performance metrics

---

## Conclusion

The Agentic TalkDoc Platform provides a robust, scalable foundation for building white-labeled healthcare platforms with AI agent automation. The architecture prioritizes:

- **Security**: Database-per-tenant, HIPAA compliance, comprehensive audit trails
- **Flexibility**: Specialty-agnostic core, configurable per tenant
- **Scalability**: Serverless deployment, connection pooling, caching
- **Reliability**: Autonomous agents with retry logic, error handling, review flags

This foundation supports the migration of the existing TalkDoc platform and enables rapid expansion to new specialties and customer segments.
