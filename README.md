# Context Mind

A local-first codebase assistant being built to answer questions about Git
repositories with references to the relevant source code.

The backend currently scans local repositories, splits source files into chunks,
and stores the chunks and locally generated embeddings in PostgreSQL with
pgvector, retrieves relevant chunks for questions, and generates repository-aware
answers with source references through Ollama. It also supports standalone chat.

## Current features

- Scan a local Git working tree, respecting Git ignore rules and excluding known
  secret files, environment files, binaries, and generated directories.
- Split source files into overlapping chunks with file paths and line references.
- Save repository snapshots in PostgreSQL using versioned Alembic migrations.
- Generate embeddings locally through Ollama and store them with pgvector.
- Reuse embeddings for unchanged content and batch new content for inference.
- Preserve the previous snapshot if indexing fails.
- Search an indexed repository with question embeddings and pgvector cosine similarity.
- Return ranked chunk content with file paths, line ranges, and similarity scores.
- Generate answers from bounded retrieved context with numbered source references.
- Send standalone questions to a configurable local Ollama chat model.

**Progress:** phases 0-10 are implemented, including a minimal React interface for
indexing repositories and asking questions with source references. A fixed-corpus
evaluation runner separates retrieval, answer quality, and hallucination checks.
Full-stack Dockerization is the next phase.

## Technology

| Component               | Technology                               |
| ----------------------- | ---------------------------------------- |
| Backend                 | Python 3.11+, FastAPI, Pydantic          |
| Persistence             | PostgreSQL 17, SQLAlchemy, Alembic       |
| Vector storage          | pgvector                                 |
| Local inference         | Ollama                                   |
| Default embedding model | `nomic-embed-text:v1.5` (768 dimensions) |
| Tests                   | pytest, HTTPX                            |
| Frontend                | React, TypeScript, Vite, Vitest           |
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

### Frontend

Requires Node.js 22.12+ (Node 24 LTS recommended) and npm. With the API running on
`127.0.0.1:8000`, open a second terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. Enter an absolute Git repository path on the backend
machine, click **Index repository**, then ask a question. Repositories indexed in
this page session appear in the selector. Refreshing clears the selector; indexing
the same path again reuses unchanged embeddings. Re-index after source edits.
The page displays progress, service errors, the answer, and numbered source lines.

Vite proxies `/api` requests to FastAPI, keeping browser requests on one origin.
Both development servers bind to localhost. No cloud API key is needed.
See the [frontend guide](docs/development.md#react-frontend-phase-ten) for checks
and limitations.

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
| `POST /api/repositories/{id}/search` | Retrieve ranked source chunks for a question |
| `POST /api/repositories/{id}/chat` | Generate a repository-grounded answer with sources |

After indexing, use the returned repository `id` in the search endpoint with:

```json
{"question": "How is repository indexing implemented?", "top_k": 5}
```

`top_k` is optional and defaults to `RETRIEVAL_TOP_K` (5); allowed values are 1-20.
Search returns matching source text and references. Send the same body to
`POST /api/repositories/{id}/chat` to generate an answer with a `sources` list of
`source_id`, `file_path`, `start_line`, and `end_line`. Citations such as `[1]`
refer to these source IDs. See the [RAG guide](docs/development.md#rag-pipeline-phase-eight)
for manual verification and limitations.

## Tests

Frontend checks, from `frontend`:

```powershell
npm test
npm run build
```

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
- [Evaluation guide](docs/evaluation.md): fixed questions, local runner, scoring, and known limitations.
- [Project instructions](PROJECT_AGENT_INSTRUCTIONS.md): scope, architecture constraints, and implementation phases.
- [Future ideas](docs/future-ideas.md): possibilities outside the current implementation.
