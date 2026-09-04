# How to Run ArchAI on Windows

Use PowerShell in the repository root:

```powershell
Set-Location 'D:\sw project\Smart-Software-Architect'
```

## First-Time Setup

Required tools:

- Node.js 18 or newer: `node --version`
- npm 9 or newer: `npm --version`
- Python 3.12 or newer: `python --version`
- Ollama: `ollama --version`

Install the JavaScript packages, create `backend\.venv`, and install the Python packages:

```powershell
npm run setup
```

Install the configured Ollama model once:

```powershell
ollama pull qwen3:1.7b
```

If the terminal was open while Ollama was installed and `ollama` is not found, close it and open a new PowerShell window. Ollama's Windows app normally starts its local server automatically.

Verify Ollama directly:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

ArchAI uses SQLite locally, so PostgreSQL is not required. For known domains, ArchAI can use its built-in blueprints. For unseen domains, Ollama analyzes the raw brief before any fallback and returns schema-validated requirements, actors, entities, workflows, integrations, data characteristics, and open questions. If Ollama is stopped, unseen-domain generation remains available but intentionally returns a conservative extraction with unresolved details instead of pretending a generic template is accurate.

## Daily Run

The recommended workflow uses one terminal. Run this only from the repository root:

```powershell
npm run dev
```

It starts both services:

- Frontend: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8010`
- API docs: `http://127.0.0.1:8010/api/v1/docs`
- Ollama: `http://127.0.0.1:11434`

Press `Ctrl+C` once to stop the frontend and backend.

## Two-Terminal Alternative

Use this only when you want separate logs. Both commands still run from the repository root.

Terminal 1:

```powershell
npm run dev:backend
```

Terminal 2:

```powershell
npm run dev:frontend
```

Do not run `npm run dev` in both terminals because each invocation starts both services.
For backend hot reload while using separate terminals, run `npm run dev:backend:reload` in Terminal 1.

## Test Everything

Keep `npm run dev` running, then use a second terminal:

```powershell
npm test
npm run lint
npm run build
npm run smoke
```

`npm run smoke` creates a real workspace, submits clarification answers, applies a change, reloads the workspace, and verifies Markdown and PDF exports.

## Ollama Status

Open `http://127.0.0.1:5173/settings`. The Backend Health panel distinguishes these states:

- `qwen3:1.7b ready`: Ollama is running and the model is installed.
- `unreachable`: start the Ollama Windows app.
- `qwen3:1.7b not installed`: run `ollama pull qwen3:1.7b`.
- `disabled`: set `ARCHAI_OLLAMA_ENABLED=true` in `backend\.env`.

The local backend configuration is read from `backend\.env`. A fresh copy can be created with:

```powershell
Copy-Item .env.example backend\.env
```

The frontend defaults to port `8010`. To override it, create `frontend\.env.local` containing:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8010/api/v1
```

## Port Checks

To see which processes own the local ports:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5173,8010,11434 |
  Select-Object LocalPort, OwningProcess
```

If a port is occupied, stop the known application that owns it or change the matching backend and frontend configuration together. Do not terminate an unknown process blindly.

## Docker

Docker is optional:

```powershell
docker compose up --build
```

The Docker deployment uses frontend port `3000` and backend port `8000`; those ports are intentionally different from the local development configuration.
