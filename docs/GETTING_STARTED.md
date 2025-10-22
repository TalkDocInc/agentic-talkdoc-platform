# Getting Started with Agentic TalkDoc Platform

## Quick Start

### Prerequisites

- Python 3.12+
- MongoDB 7.0+
- Redis 7.0+
- Node.js 20+ (for frontends)
- Docker & Docker Compose (optional, for containerized setup)

### Option 1: Docker Compose (Recommended for Development)

1. **Clone the repository**
   ```bash
   cd agentic_talkdoc
   ```

2. **Start all services**
   ```bash
   docker-compose up -d
   ```

3. **Verify services are running**
   ```bash
   docker-compose ps
   ```

4. **Access the platform**
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Admin Console: http://localhost:3000

5. **View logs**
   ```bash
   docker-compose logs -f backend
   ```

### Option 2: Manual Setup

#### Backend Setup

1. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Start MongoDB and Redis**
   ```bash
   # MongoDB
   mongod --dbpath /path/to/data/db

   # Redis
   redis-server
   ```

5. **Run the backend**
   ```bash
   cd platform_core
   uvicorn api_gateway.main:app --reload --host 0.0.0.0 --port 8000
   ```

#### Frontend Setup (Admin Console)

1. **Install dependencies**
   ```bash
   cd white-label-ui/admin-console
   npm install
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env.local
   # Edit .env.local
   ```

3. **Start development server**
   ```bash
   npm run dev
   ```

## First Steps

### 1. Create Your First Tenant

```bash
curl -X POST http://localhost:8000/platform/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Clinic",
    "subdomain": "testclinic",
    "primary_contact_email": "admin@testclinic.com",
    "primary_contact_name": "John Doe",
    "enabled_specialties": ["primary_care"],
    "primary_specialty": "primary_care"
  }'
```

### 2. Verify Tenant Creation

```bash
curl http://localhost:8000/platform/tenants/testclinic_YYYYMMDD
```

### 3. Check Tenant Health

```bash
curl http://localhost:8000/platform/tenants/testclinic_YYYYMMDD/health
```

### 4. Access Tenant-Specific Endpoints

```bash
curl http://localhost:8000/health \
  -H "X-Tenant-ID: testclinic_YYYYMMDD"
```

## Next Steps

- [Architecture Overview](./architecture.md)
- [Agent Development Guide](./agent-development.md)
- [Tenant Configuration](./tenant-configuration.md)
- [API Reference](./api-reference.md)

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=platform_core --cov=agents

# Run specific test file
pytest tests/test_tenant_management.py
```

### Code Formatting

```bash
# Format code
black platform_core agents

# Lint code
ruff platform_core agents

# Type checking
mypy platform_core
```

### Database Migrations

```bash
# Initialize platform database
python scripts/init_platform_db.py

# Create new tenant
python scripts/create_tenant.py --name "My Clinic" --subdomain myclinic
```

## Troubleshooting

### MongoDB Connection Issues

```bash
# Check MongoDB is running
mongosh --eval "db.adminCommand('ping')"

# Check connection string in .env
echo $PLATFORM_MONGO_DB_URL
```

### Redis Connection Issues

```bash
# Check Redis is running
redis-cli ping

# Should return: PONG
```

### Port Conflicts

If ports 8000, 3000, 27017, or 6379 are already in use:

```bash
# Find process using port
lsof -i :8000

# Kill process (macOS/Linux)
kill -9 <PID>
```

## Support

For issues or questions:
- GitHub Issues: https://github.com/talkdoc/agentic-talkdoc/issues
- Documentation: https://docs.talkdoc.com
- Email: support@talkdoc.com
