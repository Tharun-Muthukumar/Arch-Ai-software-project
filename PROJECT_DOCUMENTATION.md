# ArchAI - Software Architecture Decision Engine

## What ArchAI Does

ArchAI is a web application that takes a plain-English project brief and automatically generates a complete software architecture package. You describe what you want to build, and ArchAI produces:

- Structured requirements (actors, functional/non-functional requirements, constraints)
- Three architecture alternatives (Modular Monolith, Microservices, Serverless) with weighted comparison scores
- Seven UML diagrams (Use Case, Activity, Sequence, Class, ER, Component, Deployment)
- Database schema design with SQL DDL
- REST API endpoint specifications
- Deployment recommendations (Docker, Kubernetes, CI/CD)
- Exportable Markdown and PDF reports

---

## Tech Stack

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| React | 19.2 | UI framework |
| TypeScript | 6.0 | Type safety |
| Vite | 8.2 | Build tool & dev server |
| TailwindCSS | 3.4 | Utility-first styling |
| React Router | 7.18 | Client-side routing |
| TanStack React Query | 5.101 | Server state management & caching |
| Mermaid | 11.16 | Diagram rendering (flowcharts, ER, sequence, etc.) |
| Recharts | 3.10 | Radar chart for architecture comparison |
| React Markdown | 10.1 | Markdown report rendering |
| Vitest | 4.1 | Unit testing |

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.116 | REST API framework |
| SQLAlchemy | 2.0 | ORM & database access |
| Pydantic | 2.11 | Data validation & schemas |
| Uvicorn | 0.35 | ASGI server |
| ReportLab | 4.4 | PDF generation |
| httpx | 0.28 | HTTP client (Ollama integration) |
| pwdlib + Argon2 | 0.3 | Secure password hashing |
| email-validator | 2.3 | Account email validation |
| pytest | 8.4 | Testing |
| Ollama (qwen3:8b) | Optional | Schema-validated extraction from raw briefs for unseen domains |

### Database
- **Development:** SQLite (zero-config, file-based)
- **Production:** PostgreSQL 16 (via Docker)

### Infrastructure
- Docker & Docker Compose for containerized deployment
- Nginx for production frontend serving

---

## How It Works - The Pipeline

When a user submits a project brief, ArchAI runs a 9-step generation pipeline:

```
1. Requirement Analyzer   -->  Extracts actors, features, constraints from the brief
2. Clarification Engine   -->  Identifies gaps, generates follow-up questions
3. Architecture Generator -->  Creates 3 architecture alternatives
4. Comparison Engine      -->  Scores each architecture on 12 weighted metrics
5. Recommendation Engine  -->  Picks the best option with reasoning
6. Database Generator     -->  Generates entity-relationship schema + SQL DDL
7. API Generator          -->  Designs REST endpoint specifications
8. Deployment Generator   -->  Recommends infrastructure and deployment strategy
9. Diagram Generator      -->  Produces 7 UML diagrams (Mermaid + PlantUML)
```

After this, a Documentation Generator compiles everything into a Markdown report and PDF.

### Domain-Aware Generation

The system recognizes four domains out of the box:
- **EV Charging Booking Platform** - stations, chargers, bookings, sessions, payments
- **Online Pharmacy** - products, prescriptions, orders, inventory, shipments
- **E-Commerce** - products, orders, payments, shipments
- **Learning Platform** - courses, enrollments, lessons, submissions, notifications

Known domains use built-in requirement knowledge. An unrecognized brief is sent raw to Ollama before any fallback is constructed. Qwen returns a constrained JSON structure containing the domain, requirements, actors, entities, workflows, integrations, data characteristics, assumptions, and open questions. Pydantic validates that response, and grounding guards remove unsupported numeric constraints and unsolicited named technologies. The validated model then drives the same architecture, scoring, database, API, diagram, deployment, and documentation pipeline. No new domain file is needed.

### Ollama Extraction and Fallback

If Ollama is running locally with the `qwen3:8b` model, unknown-domain extraction uses temperature zero, a fixed seed, and a Pydantic-derived JSON schema. Explicit restrictions and integration clauses from the source text are preserved after extraction. If Ollama is unavailable or its output fails validation, ArchAI retains the raw user requirement, marks the domain and scale as unknown, and asks clarification questions instead of substituting a generic digital-platform blueprint.

---

## Project Structure

```
software-project/
|
|-- backend/
|   |-- app/
|   |   |-- main.py                  # FastAPI entry point
|   |   |-- core/
|   |   |   |-- config.py            # Environment settings (pydantic-settings)
|   |   |   |-- database.py          # SQLAlchemy engine & session
|   |   |   |-- logging.py           # Logging configuration
|   |   |-- api/
|   |   |   |-- deps.py              # Dependency injection (DB session)
|   |   |   |-- routes/
|   |   |       |-- health.py        # GET /api/v1/health
|   |   |       |-- workspaces.py    # CRUD + clarifications + changes
|   |   |-- models/
|   |   |   |-- workspace.py         # SQLAlchemy model (single workspaces table)
|   |   |-- schemas/
|   |   |   |-- domain.py            # All Pydantic models (40+ schemas)
|   |   |-- repositories/
|   |   |   |-- workspace_repository.py  # Database operations
|   |   |-- services/
|   |       |-- workspace_orchestrator.py # Central orchestrator (runs the pipeline)
|   |       |-- requirement_analyzer.py   # Step 1: Extract requirements
|   |       |-- clarification_engine.py   # Step 2: Generate follow-up questions
|   |       |-- architecture_generator.py # Step 3: Generate 3 architecture options
|   |       |-- comparison_engine.py      # Step 4: Score & compare architectures
|   |       |-- recommendation_engine.py  # Step 5: Pick best architecture
|   |       |-- database_generator.py     # Step 6: Generate DB schema + SQL
|   |       |-- api_generator.py          # Step 7: Generate API endpoints
|   |       |-- deployment_generator.py   # Step 8: Deployment recommendations
|   |       |-- diagram_generator.py      # Step 9: Generate 7 UML diagrams
|   |       |-- documentation_generator.py # Markdown + PDF export
|   |       |-- impact_analyzer.py        # Impact analysis for change requests
|   |       |-- ai/
|   |           |-- client.py            # Ollama integration
|   |           |-- prompts.py           # LLM prompt templates
|   |-- tests/                     # pytest test suite
|   |-- migrations/                # SQL migration scripts
|   |-- requirements.txt           # Python dependencies
|   |-- Dockerfile
|
|-- frontend/
|   |-- src/
|   |   |-- main.tsx               # React entry point
|   |   |-- App.tsx                # Route definitions
|   |   |-- index.css              # Global styles & design tokens
|   |   |-- pages/
|   |   |   |-- DashboardPage.tsx         # Create briefs, view workspaces
|   |   |   |-- RequirementWizardPage.tsx # View structured requirements
|   |   |   |-- ArchitectureStudioPage.tsx # Compare architectures
|   |   |   |-- ComparisonPage.tsx        # Radar chart + scorecard table
|   |   |   |-- DiagramsPage.tsx          # View all 7 diagrams
|   |   |   |-- DocsPage.tsx              # View & export reports
|   |   |   |-- SettingsPage.tsx          # API config & health check
|   |   |   |-- LandingPage.tsx           # Product overview
|   |   |-- components/
|   |   |   |-- layout/            # AppShell, ThemeToggle
|   |   |   |-- workspace/         # WorkspaceForm, ClarificationPanel, etc.
|   |   |   |-- diagrams/          # MermaidDiagram, ArchitectureFlow
|   |   |   |-- charts/            # RadarComparisonChart
|   |   |   |-- docs/              # MarkdownPanel
|   |   |-- hooks/                 # useTheme, useWorkspaces
|   |   |-- lib/                   # API client, utilities, sample data
|   |   |-- types/                 # TypeScript type definitions
|   |-- package.json
|   |-- Dockerfile
|
|-- docker-compose.yml             # 3-service setup (postgres, backend, frontend)
|-- package.json                   # Root workspace scripts
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/health` | Health check (returns service status, environment, Ollama status) |
| GET | `/api/v1/workspaces` | List all workspaces |
| POST | `/api/v1/workspaces` | Create workspace from a project brief |
| GET | `/api/v1/workspaces/{id}` | Get a specific workspace |
| POST | `/api/v1/workspaces/{id}/clarifications` | Submit clarification answers, regenerate workspace |
| POST | `/api/v1/workspaces/{id}/changes` | Apply a change request (impact-aware regeneration) |
| GET | `/api/v1/workspaces/{id}/documentation/markdown` | Download Markdown report |
| GET | `/api/v1/workspaces/{id}/documentation/pdf` | Download PDF report |

---

## Workspace Lifecycle

### Phase 1: Creation
1. User enters a project brief (title, description, business context, budget, cloud preference, constraints)
2. Backend analyzes the brief and extracts requirements
3. If the system detects gaps, it generates clarification questions
4. All artifacts are generated (architectures, diagrams, DB schema, APIs, deployment plan, documentation)

### Phase 2: Clarification
1. User answers the follow-up questions (e.g., authentication method, payment integration, SLA targets)
2. Backend merges answers and regenerates all artifacts with improved accuracy
3. Completeness score updates

### Phase 3: Exploration
1. **Requirements** - View actors, functional/non-functional requirements, constraints
2. **Architecture** - Compare 3 alternatives side by side with per-metric scores
3. **Diagrams** - Browse 7 diagram types rendered from Mermaid syntax
4. **Report** - Read the full Markdown documentation or export as PDF

### Phase 4: Iteration (Change Requests)
1. User submits a change request (e.g., "add real-time notifications")
2. `ImpactAnalyzer` determines which modules are affected
3. Only affected services re-run (not the entire pipeline)
4. Impact history is tracked

---

## Architecture Comparison System

ArchAI scores each architecture on 12 metrics:

| Metric | What It Measures |
|---|---|
| Scalability | How well it handles growth |
| Performance | Response time and throughput |
| Maintainability | Ease of code changes |
| Security | Auth, data protection, compliance |
| Cost | Infrastructure and development cost |
| Reliability | Uptime and failure handling |
| Availability | Target uptime achievement |
| Deployment Complexity | How hard it is to deploy |
| Learning Curve | Team ramp-up time |
| Development Time | Speed to first release |
| Fault Isolation | Blast radius of failures |
| Operational Complexity | Day-to-day management overhead |

Weights are adjusted based on the project's scale profile:
- **Startup scale** - favors lower cost, faster development, simpler deployment
- **Growth scale** - balanced weights
- **High scale** - favors scalability, availability, fault isolation

---

## Database Design

Generated architecture state remains in the `workspaces` JSON document table:

| Column | Contents |
|---|---|
| `requirements_json` | Actors, functional/non-functional requirements, constraints |
| `clarification_json` | Questions, answers, completeness score |
| `architectures_json` | 3 architecture options with components, tech stacks, pros/cons |
| `comparison_json` | 12-metric scorecards with weights |
| `recommendation_json` | Best architecture choice with reasoning |
| `diagrams_json` | 7 diagram artifacts (Mermaid + PlantUML syntax) |
| `database_design_json` | Entities, relationships, SQL DDL |
| `api_design_json` | Endpoint specifications |
| `deployment_plan_json` | Infrastructure recommendations |
| `documentation_markdown` | Full Markdown report |
| `impact_history_json` | Change request audit trail |

Account data is normalized into five additive tables:

| Table | Purpose |
|---|---|
| `users` | Public profile fields and Argon2 password hash |
| `auth_sessions` | Revocable sessions with hashed opaque tokens and expiry |
| `conversations` | User-owned history records linked to generated workspaces |
| `conversation_messages` | User prompts, ArchAI summaries, timestamps, and result references |
| `conversation_shares` | Recipient-specific permissions, currently restricted to `VIEW` |

---

## Frontend Pages

| Page | Route | What It Shows |
|---|---|---|
| Dashboard | `/dashboard` | Create project briefs, view workspace summary, answer clarifications |
| Requirements | `/wizard` | Actors, functional/non-functional requirements, constraints, assumptions |
| Architecture | `/architecture` | Comparison table, architecture selector, component flow, tech stack, trade-offs |
| Comparison | `/comparison` | Radar chart visualization, scoring rationale, full scorecard table |
| Diagrams | `/diagrams` | 7 diagram types with Mermaid rendering, source toggle, PNG export |
| Report | `/docs` | Markdown report with Markdown/PDF download buttons |
| History | `/history` | Owned and shared conversations, messages, result reopening, sharing, and revocation |
| Profile | `/profile` | Account details and phone number updates |
| Settings | `/settings` | API URL config, theme toggle, backend health check |

---

## Running the Project

### Development (without Docker)
```powershell
# First run only
npm run setup
ollama pull qwen3:8b

# Daily development: starts frontend and backend together
npm run dev
```

Frontend: http://127.0.0.1:5173
Backend API: http://127.0.0.1:8010

### Production (with Docker)
```bash
docker compose up --build
```

Frontend: http://localhost:3000
Backend API: http://localhost:8000
PostgreSQL: localhost:5432

### Running Tests
```bash
# Backend and frontend tests
npm test

# Full smoke test
npm run smoke
```

---

## Key Design Decisions

1. **Known blueprints plus raw-input LLM extraction** - Known domains use curated blueprints. Unknown domains go directly from the raw brief to schema-validated Ollama extraction. Without Ollama, the system remains usable but intentionally leaves domain details unresolved.

2. **Workspace JSON plus normalized accounts** - Generated architecture state stays in one workspace JSON document, while users, sessions, conversation messages, and sharing permissions use normalized relational tables.

3. **Impact-aware regeneration** - Change requests don't regenerate everything. The `ImpactAnalyzer` maps keywords to affected modules and only re-runs those services.

4. **Dual diagram syntax** - Every diagram is generated in both Mermaid (for in-browser rendering) and PlantUML (for external tooling).

5. **Domain-aware generation without unknown-domain files** - Pre-built blueprints cover EV Charging, Online Pharmacy, E-Commerce, and Learning. Unseen domains use Qwen's pretrained knowledge and source-grounding safeguards rather than a generic template.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ARCHAI_APP_NAME` | ArchAI | Application name |
| `ARCHAI_ENVIRONMENT` | development | Environment label |
| `ARCHAI_DATABASE_URL` | sqlite:///./archai.db | Database connection string |
| `ARCHAI_ALLOWED_ORIGINS` | localhost:5173,4173,3000 | CORS allowed origins |
| `ARCHAI_OLLAMA_ENABLED` | true | Enable raw-input unseen-domain extraction and known-domain narrative refinement |
| `ARCHAI_OLLAMA_BASE_URL` | http://localhost:11434 | Ollama server URL |
| `ARCHAI_OLLAMA_MODEL` | qwen3:8b | Model to use for structured extraction |
| `ARCHAI_AUTH_SESSION_HOURS` | 8 | Lifetime of a revocable login session |
| `ARCHAI_LOG_LEVEL` | INFO | Logging level |
