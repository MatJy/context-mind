# Context Mind

A local-first codebase assistant being built to answer questions about Git
repositories with references to the relevant source code.

The backend currently scans local repositories, splits source files into chunks,
and stores the chunks and locally generated embeddings in PostgreSQL with
pgvector. It also supports standalone chat through Ollama. Repository-aware
answers are still in development.

## Current features

- Scan a local Git working tree, respecting Git ignore rules and excluding known
  secret files, environment files, binaries, and generated directories.
- Split source files into overlapping chunks with file paths and line references.
- Save repository snapshots in PostgreSQL using versioned Alembic migrations.
- Generate embeddings locally through Ollama and store them with pgvector.
- Reuse embeddings for unchanged content and batch new content for inference.
- Preserve the previous snapshot if indexing fails.
- Send standalone questions to a configurable local Ollama chat model.

**Progress:** phases 0-6 are implemented. Next is semantic retrieval, followed by
repository-aware answers, evaluation, a React interface, and home-server
deployment. There is no semantic search endpoint or frontend yet.

## Technology

| Component               | Technology                               |
| ----------------------- | ---------------------------------------- |
| Backend                 | Python 3.11+, FastAPI, Pydantic          |
| Persistence             | PostgreSQL 17, SQLAlchemy, Alembic       |
| Vector storage          | pgvector                                 |
| Local inference         | Ollama                                   |
| Default embedding model | `nomic-embed-text:v1.5` (768 dimensions) |
| Tests                   | pytest, HTTPX                            |
| Development database    | Docker Compose with a persistent volume  |

No cloud AI API key is required. Inference runs on the configured Ollama host,
which defaults to your own computer. Model downloads require internet access.

## Quick start

Requires Python 3.11+, Git, a running Ollama service, and Docker Desktop (or Docker
Engine with Compose on Linux). The backend runs on the host; the development
database runs in Docker.

From the repository root, using PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "./backend[dev]"
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

In your private `.env`, set `POSTGRES_PASSWORD` to a password of your choice and
set `DATABASE_URL` to:

```text
postgresql+psycopg://context_mind:<URL-encoded-password>@localhost:5433/context_mind
```

Use the same password in both settings; URL-encode special characters in the
connection URL. Keep `.env.example` free of credentials.

Download the default models, start the database, apply migrations, and run the API:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text:v1.5
docker compose --project-name context-mind --env-file .env -f infra/compose.postgres.yml up -d --wait
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --app-dir backend --reload
```

Open <http://127.0.0.1:8000/docs> to try the API. To index a repository, use
`POST /api/repositories/index` with an absolute path on the backend machine:

```json
{
    "path": "C:/path/to/repository",
    "chunking": { "max_lines": 40, "overlap_lines": 5 }
}
```

The database is available on `localhost:5433`. Keep the API bound to localhost
while using these unauthenticated local-file endpoints.

For Linux/macOS commands, configuration options, native PostgreSQL setup,
limitations, and troubleshooting, see the [development guide](docs/development.md).

## API

| Endpoint                        | Purpose                                           |
| ------------------------------- | ------------------------------------------------- |
| `GET /api/health`               | Basic application health                          |
| `POST /api/chat`                | Standalone Ollama chat without repository context |
| `POST /api/repositories/scan`   | Preview accepted source files                     |
| `POST /api/repositories/chunks` | Preview source chunks and line references         |
| `POST /api/repositories/index`  | Persist chunks and their local embeddings         |

## Tests

With the virtual environment activated:

```powershell
Set-Location backend
python -m pytest -q
```

The default suite uses isolated test databases and mocked model responses. Git
is required; running PostgreSQL and Ollama services are only needed for the
opt-in [local integration test](docs/development.md#tests).

## Documentation

- [Development guide](docs/development.md): setup, settings, API behavior, and verification.
- [Project instructions](PROJECT_AGENT_INSTRUCTIONS.md): scope, architecture constraints, and implementation phases.
- [Future ideas](docs/future-ideas.md): possibilities outside the current implementation.
