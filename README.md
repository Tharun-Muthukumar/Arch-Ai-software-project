# ArchAI

ArchAI is a production-style software architecture decision engine that turns a natural language project brief into requirements, architecture options, comparison scorecards, diagrams, database design, API outlines, deployment recommendations, and exportable documentation.

## Tech stack

- Frontend: React, TypeScript, TailwindCSS, Mermaid, React Flow
- Backend: FastAPI, SQLAlchemy, Pydantic
- AI integration: Ollama with `qwen3:8b` and schema-validated raw-brief extraction for unseen domains
- Persistence: PostgreSQL-ready with zero-friction SQLite local fallback
- Accounts: Argon2 password hashing, revocable cookie sessions, private history, and read-only sharing
- Documentation: Markdown and PDF export

## Monorepo layout

```text
frontend/    React application
backend/     FastAPI application
docker/      Shared container configuration
docs/        Supporting project documentation
```

## Quick start

### From the repository root

```bash
npm run setup
npm run dev
```

This starts:

- FastAPI on `http://127.0.0.1:8010`
- React on `http://127.0.0.1:5173`

Once both servers are up, run this end-to-end API smoke test from a second terminal:

```bash
npm run smoke
```

### Backend (separate terminal)

```bash
npm run dev:backend
```

Use `npm run dev:backend:reload` when running the backend by itself during active backend development.

### Frontend (separate terminal)

```bash
npm run dev:frontend
```

### Optional full stack with Docker

```bash
docker compose up --build
```

The backend will run when Ollama is unavailable, but unseen domains then use a deliberately conservative result based on the user's text and clarification questions. With Ollama enabled, known domains may use their built-in blueprints while unseen domains are extracted directly from the raw brief. Start Ollama and run `ollama pull qwen3:8b` once. The Settings page reports whether Ollama and the configured model are ready.

## Key capabilities

- Requirement analysis with structured JSON output
- Clarification question generation and answer persistence
- Three architecture alternatives with deterministic scoring
- Recommendation reasoning with why/why-not breakdowns
- Mermaid and PlantUML generation for multiple diagram types
- Database schema, API design, deployment plan, and documentation generation
- Incremental impact-aware updates for change requests
- User profiles and automatically persisted conversation history
- Owner-controlled, read-only conversation sharing with revocation

## Account data and migrations

SQLite development databases create the account and history tables automatically when the backend starts. For an existing PostgreSQL deployment, apply the additive migration before starting the updated backend:

```bash
psql "$DATABASE_URL" -f backend/migrations/002_accounts_history.sql
```

Authentication uses an opaque random session token in an `HttpOnly`, `SameSite=Lax` cookie. Only a SHA-256 hash of the token is stored in the database; passwords are stored as Argon2 hashes.

## Verification checklist

- Backend tests: `pytest`
- Frontend tests: `npm run test -- --run`
- Frontend production build: `npm run build`
- End-to-end API smoke test: `npm run smoke`
