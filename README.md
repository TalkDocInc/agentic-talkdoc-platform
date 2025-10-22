# Agentic TalkDoc Platform

## Overview

Agentic TalkDoc is a **specialty-agnostic, multi-tenant healthcare platform** that enables healthcare organizations to launch white-labeled clinician marketplaces with AI agents automating billing, care coordination, and patient engagement.

## Architecture

- **Multi-Tenant Design**: Database-per-tenant isolation for maximum security and compliance
- **Agent Orchestration**: 15+ specialized AI agents for autonomous healthcare operations
- **White-Label Ready**: Full customization of branding, features, and workflows per tenant
- **Specialty Agnostic**: Configurable for mental health, primary care, psychiatry, and more

## Key Features

### 🤖 AI Agents (15 Specialized Agents)

#### Revenue Cycle Agents
1. Insurance Verification Agent
2. Medical Coding Agent
3. Claims Generation Agent
4. Denial Prediction Agent
5. Appeals Management Agent

#### Care Coordination Agents
6. Patient Intake Agent
7. Smart Scheduling Agent
8. Follow-up Coordination Agent
9. Cross-Provider Communication Agent
10. Care Plan Management Agent

#### Patient Engagement Agents
11. AI Health Advisor
12. Appointment Assistant Agent
13. Patient Education Agent
14. Symptom Assessment Agent
15. Outcomes Tracking Agent

## Technology Stack

- **Backend**: Python 3.12, FastAPI, Motor (async MongoDB)
- **Agent Framework**: LangGraph, OpenAI/Anthropic
- **Task Queue**: AWS SQS, Step Functions
- **Database**: MongoDB (database-per-tenant)
- **Deployment**: AWS Lambda, Serverless Framework
- **Frontend**: React, Vite, Tailwind CSS
- **Video**: AWS Chime SDK
- **Caching**: Redis

## Project Structure

```
agentic_talkdoc/
├── platform_core/              # Core multi-tenant platform
│   ├── tenant_management/      # Tenant provisioning and configuration
│   ├── agent_orchestration/    # Agent framework and workflow engine
│   ├── auth/                   # Multi-tenant authentication (NEW!)
│   ├── shared_services/        # Tenant routing, video, email
│   └── api_gateway/            # Main FastAPI application
├── agents/                     # 15 specialized agents
│   ├── revenue_cycle/          # Billing and claims agents
│   ├── care_coordination/      # Scheduling and coordination agents
│   └── patient_engagement/     # Patient interaction agents
├── specialty_configs/          # Template configurations per specialty
│   ├── mental_health/
│   ├── psychiatry/
│   └── primary_care/
├── white_label_ui/             # Configurable frontend templates
│   ├── patient_portal/
│   ├── clinician_dashboard/
│   ├── coordinator_dashboard/
│   └── admin_console/
├── docs/                       # Documentation
└── tests/                      # Test suites
```

## Quick Start

### Prerequisites

- Python 3.12+
- MongoDB 7.0+
- Redis 7.0+
- AWS Account (for deployment)
- Node.js 20+ (for frontends)

### Backend Setup

```bash
cd platform-core
cp .env.example .env
# Edit .env with your configuration

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python scripts/init_platform_db.py

# Start development server
uvicorn api-gateway.main:app --reload
```

### Frontend Setup

```bash
cd white-label-ui/admin-console
npm install
npm run dev
```

## Development Phases

- **Phase 1** (Months 1-3): Foundation - Multi-tenant core + agent framework
- **Phase 2** (Months 4-6): Core Agents - Build 10 highest-impact agents
- **Phase 3** (Months 7-9): TalkDoc Migration - Migrate existing TalkDoc as first tenant
- **Phase 4** (Months 10-12): Market Expansion - Complete agent suite, onboard second tenant

## Configuration

### Tenant Configuration

Each tenant has a configuration defining:
- Branding (logo, colors, domain)
- Enabled features and agents
- Specialty-specific settings
- Insurance integrations
- Compliance requirements

Example tenant configuration:

```python
{
    "tenant_id": "talkdoc_prod",
    "name": "TalkDoc",
    "branding": {
        "logo_url": "https://cdn.talkdoc.com/logo.png",
        "primary_color": "#4F46E5",
        "domain": "talkdoc.com"
    },
    "specialties": ["mental_health_therapy", "psychiatry"],
    "features": {
        "agents": {
            "billing": True,
            "scheduling": True,
            "chat": True
        },
        "ml_models": {
            "depression_detection": True
        }
    }
}
```

## Security & Compliance

- **HIPAA Compliant**: Encryption at rest and in transit
- **Audit Logging**: All agent actions logged with full traceability
- **Role-Based Access**: Configurable per tenant
- **Data Isolation**: Database-per-tenant architecture
- **MFA Support**: Two-factor authentication for all users

## Business Model

- Platform Subscription: $5K-$25K/month base fee
- Per-Clinician Fee: $50-$150/clinician/month
- Agent Usage Pricing: $0.10-$2.00 per agent action
- Performance-Based: Optional 5-10% revenue share
- Implementation Fee: $10K-$100K one-time

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Agent Development Guide](docs/agent-development.md)
- [Tenant Onboarding](docs/tenant-onboarding.md)
- [API Reference](docs/api-reference.md)
- [White-Labeling Guide](docs/white-labeling.md)

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=platform-core --cov=agents

# Run specific test suite
pytest tests/agents/revenue-cycle/
```

## Deployment

```bash
# Deploy to development
serverless deploy --stage dev

# Deploy to production
serverless deploy --stage prod
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License - See [LICENSE](LICENSE) file for details

## Contact

For questions or support, contact: support@talkdoc.com
