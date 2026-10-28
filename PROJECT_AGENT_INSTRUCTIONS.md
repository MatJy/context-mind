# PROJECT_AGENT_INSTRUCTIONS.md
## AI Codebase Assistant + Home Server

You are the coding agent for this project. Follow this document as the source of truth for scope, sequencing, architecture, and implementation constraints.

---

# 1. Project Goal

Build a portfolio-quality **AI Codebase Assistant** that can index a local Git repository, retrieve relevant code using RAG, and answer questions about the codebase with source references.

The MVP must also be deployable to a self-hosted Linux home server.

The project is intended to demonstrate practical experience with:

- Python
- FastAPI
- PostgreSQL
- pgvector
- embeddings
- semantic retrieval
- RAG
- Ollama / local LLM
- local embedding model
- optional OpenAI API provider later
- React + TypeScript
- Docker
- Docker Compose
- Ubuntu Server
- deployment and basic server operations

Do not expand the project beyond the defined MVP unless explicitly requested.

---

# 2. Core MVP Flow

The final MVP should work like this:

```text
1. User selects or provides a repository

2. Backend scans the repository

3. Unsafe and irrelevant files are excluded

4. Source files are split into chunks

5. Embeddings are generated for chunks

6. Chunks and embeddings are stored in PostgreSQL + pgvector

7. User asks a question about the repository

8. The question is embedded

9. pgvector retrieves the most relevant chunks

10. Backend builds the LLM prompt

11. A local LLM running through Ollama analyzes the retrieved code

12. User receives:
    - an answer
    - source file paths
    - line ranges / source references

13. The application runs using Docker Compose

14. The application is deployed to an Ubuntu Server home server
```

---

# 3. Technology Decisions

Use the following unless explicitly changed later.

## Backend

- Python
- FastAPI
- Pydantic
- pytest

## Frontend

- React
- TypeScript
- Vite

Keep the frontend intentionally simple.

## Database

- PostgreSQL
- pgvector

## AI

MVP:
- Ollama for local LLM inference
- a local embedding model
- no cloud AI dependency required for the core MVP

The application architecture must keep LLM and embedding providers replaceable so an OpenAI API provider can be added later without rewriting the whole application.

Default MVP provider strategy:

```text
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=local
```

A later optional cloud configuration may use:

```text
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
```

Do not make OpenAI API a requirement for the initial MVP.

## Infrastructure

- Docker
- Docker Compose
- Ubuntu Server LTS for deployment

---

# 4. Architecture Principles

Keep responsibilities separated.

Suggested backend responsibilities:

```text
api/
    HTTP routes

schemas/
    request/response models

services/
    repository ingestion
    chunking
    embeddings
    retrieval
    RAG orchestration
    LLM provider

models/
    database models

core/
    configuration
    shared infrastructure
```

Do not create unnecessary abstractions.

Prefer simple, explicit code over framework-heavy abstractions.

Do not use LangChain or LlamaIndex in the MVP unless explicitly requested.

---

# 5. Suggested Repository Structure

Use approximately this structure unless there is a strong reason to change it:

```text
ai-codebase-assistant/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   └── Dockerfile
│
├── infra/
│   └── docker-compose.yml
│
├── docs/
│   ├── architecture.md
│   └── decisions.md
│
├── .env.example
├── .gitignore
├── PROJECT_AGENT_INSTRUCTIONS.md
└── README.md
```

---

# 6. Required Development Order

Implement the project in phases.

Do not skip ahead unless explicitly instructed.

---

## Phase 0 — Project Initialization

Create the initial project structure.

Required:
- Git-friendly structure
- backend directory
- frontend directory
- `.gitignore`
- `.env.example`
- README placeholder
- this instruction file

Do not implement:
- database
- embeddings
- RAG
- Docker
- frontend functionality

---

## Phase 1 — FastAPI Base

Implement only the basic backend.

Required endpoint:

```http
GET /api/health
```

Expected response:

```json
{
  "status": "ok"
}
```

Required:
- FastAPI app
- configuration structure
- type hints
- health route
- pytest test for health route
- clear local run instructions

Do not add:
- Ollama
- OpenAI
- PostgreSQL
- RAG
- Docker
- React functionality

---

## Phase 2 — Basic Local LLM Integration

Add one simple endpoint:

```http
POST /api/chat
```

Input example:

```json
{
  "question": "Explain dependency injection."
}
```

Required:
- Ollama client/integration
- configurable local model name
- configuration through environment variables
- request validation
- error handling
- timeout handling
- clear error when Ollama is not running
- basic test strategy

Default local configuration should be similar to:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<selected-local-model>
```

Do not add RAG yet.
Do not add OpenAI yet.

The purpose of this phase is only to verify:

```text
client
→ FastAPI
→ local Ollama service
→ local LLM
→ FastAPI
→ response
```

Keep the model name configurable rather than hard-coding it throughout the codebase.

---

## Phase 3 — Repository Ingestion

Add support for scanning one local repository.

Initially support source files such as:

```text
.py
.js
.ts
.tsx
.jsx
.json
.md
```

Exclude at minimum:

```text
.git/
node_modules/
dist/
build/
coverage/
.env
.env.*
*.pem
*.key
binary files
```

Required output per source file:
- file path
- text content
- enough metadata for later chunking

Security requirement:
Never ingest secrets or environment files.

---

## Phase 4 — Chunking

Split source files into smaller chunks.

Initial implementation may use a simple strategy.

Each chunk must include metadata such as:

```json
{
  "file_path": "backend/auth.py",
  "start_line": 20,
  "end_line": 65,
  "content": "..."
}
```

Use a small overlap where appropriate.

Do not over-engineer AST-aware chunking in the MVP.

---

## Phase 5 — PostgreSQL Persistence

Add PostgreSQL.

Store at minimum:

### Repository

```text
id
name
path
indexed_at
```

### CodeChunk

```text
id
repository_id
file_path
content
start_line
end_line
content_hash
```

Use migrations.

Keep database access explicit and understandable.

---

## Phase 6 — Local Embeddings

Generate an embedding for each code chunk using a local embedding model.

Store embeddings in PostgreSQL using pgvector.

Required:
- embedding provider abstraction
- local embedding provider as the MVP default
- configurable embedding model name
- batch where practical
- error handling
- avoid re-embedding unchanged chunks where possible

The MVP must not require sending source code to an external embedding API.

Use `content_hash` or equivalent to support future re-indexing.

Keep the embedding provider replaceable so an OpenAI embedding provider can be added later.

---

## Phase 7 — Semantic Retrieval

Implement question retrieval.

Flow:

```text
question
→ embedding
→ pgvector similarity search
→ top-k chunks
```

Return:
- chunk content
- file path
- start line
- end line
- similarity/relevance value if useful

Start with a small configurable `top_k`.

Do not add complex reranking unless needed.

---

## Phase 8 — RAG Pipeline

Combine retrieval and LLM generation.

Flow:

```text
question
→ question embedding
→ retrieval
→ relevant chunks
→ prompt builder
→ LLM
→ answer + sources
```

Prompt requirements:
- use provided context
- do not invent files
- state when repository context is insufficient
- preserve source references

API response should include:
- generated answer
- source files
- line ranges

---

## Phase 9 — Evaluation

Create a small deterministic evaluation set for a known repository.

Include questions where:
- the answer exists clearly
- multiple files are needed
- the answer does not exist

Evaluate separately:
- retrieval quality
- answer quality
- hallucination behavior

Document known limitations.

---

## Phase 10 — React Frontend

Build a minimal interface.

Required:
- repository selection/index action
- question input
- submit button
- loading state
- error state
- answer display
- source display

Avoid spending significant time on visual polish.

---

## Phase 11 — Dockerization

Containerize the application.

Target services:

```text
frontend
backend
postgres
```

Use Docker Compose.

Requirements:
- persistent PostgreSQL volume
- environment variables
- health checks where useful
- clear local start/stop instructions

The full application should start using:

```bash
docker compose up
```

or equivalent.

---

## Phase 12 — Home Server Preparation

Target:
- Ubuntu Server LTS
- headless operation
- SSH administration

Prepare instructions for:
- user account
- system updates
- SSH key authentication
- firewall
- Docker Engine
- Docker Compose
- stable local IP / DHCP reservation

Do not expose the server directly to the public internet.

---

## Phase 13 — Deployment

Deploy the project to the home server.

Expected flow:

```text
git clone / pull
docker compose up -d
```

Verify:
- frontend reachable on LAN
- backend reachable
- PostgreSQL persists data
- local Ollama connectivity works for the chosen deployment architecture
- application survives container restart

Document:
- deployment commands
- update process
- log inspection
- restart process

---

# 7. Security Rules

Never commit:
- `.env`
- API keys
- passwords
- private SSH keys
- credentials
- secrets

Repository ingestion must never intentionally index:
- `.env`
- private keys
- credential files
- known secret files

Use `.env.example` with empty placeholders only.

Keep the first deployment LAN-only.

Do not configure router port forwarding unless explicitly requested later.

---

# 8. Scope Restrictions

Do NOT add the following to the MVP unless explicitly requested:

- LangChain
- LlamaIndex
- agent framework
- autonomous code editing
- automatic Git commits
- authentication
- multi-user support
- public internet deployment
- Kubernetes
- microservices
- mobile app
- calendar integration
- email integration
- Home Assistant integration
- advanced permissions
- multiple vector databases
- elaborate frontend design

---

# 9. AI Provider Strategy

The MVP is **local-first**.

Default:
- Ollama for the LLM
- local embeddings
- no OpenAI API required

Preferred provider abstractions:

```python
class LLMProvider:
    async def generate(...):
        ...
```

and:

```python
class EmbeddingProvider:
    async def embed(...):
        ...
```

Initial implementations:

```text
OllamaProvider
LocalEmbeddingProvider
```

Later optional implementations:

```text
OpenAIProvider
OpenAIEmbeddingProvider
```

Do not implement OpenAI during the initial MVP unless explicitly requested.

Keep provider-specific code behind small interfaces so the RAG pipeline does not depend directly on one AI vendor.

Important deployment note:

The application may ultimately run on the HP home server while the local LLM runs on a more powerful machine on the same trusted LAN. Do not assume the HP laptop itself must run the LLM. Keep the Ollama base URL configurable.

If the LLM runs on another LAN machine:
- do not expose Ollama directly to the public internet
- restrict access to the trusted local network
- document the dependency clearly
- handle the case where the LLM host is offline

---

# 9A. Optional Post-MVP Phase — OpenAI Provider

Only after the local-first MVP works, optionally add OpenAI as a second provider.

Goals:
- keep the same RAG pipeline
- switch providers through configuration
- compare local vs cloud quality, speed, privacy, and cost
- do not duplicate business logic

Possible configuration:

```env
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=
```

This phase is optional and must not block the MVP.

---

# 10. Quality Requirements

For each implementation phase:

1. Explain the proposed changes before coding.
2. Identify files that will be created or modified.
3. Implement only the current phase.
4. Add tests where reasonable.
5. Run tests.
6. Report test results.
7. Explain manual verification steps.
8. Do not automatically continue into the next phase.

Prefer readable code over clever code.

Use type hints.

Use clear naming.

Avoid unnecessary dependencies.

---

# 11. Learning-Oriented Agent Behavior

The user is intentionally learning while building this project.

When introducing a new technical concept in code:

- explain what is being added
- explain why it is needed
- mention the main alternative if relevant
- point out important tradeoffs
- keep explanations short and directly tied to the implementation

Do not turn the implementation into a large tutorial unless asked.

The agent should still prioritize correct, maintainable code.

---

# 12. Definition of Done for MVP

The MVP is complete when all are true:

- [ ] FastAPI backend works
- [ ] local Ollama LLM integration works
- [ ] one repository can be indexed
- [ ] unsafe files are excluded
- [ ] source code is chunked
- [ ] PostgreSQL persistence works
- [ ] pgvector is enabled
- [ ] local embeddings are generated and stored
- [ ] semantic retrieval works
- [ ] RAG answers use retrieved context
- [ ] source file references are returned
- [ ] basic evaluation exists
- [ ] React UI works
- [ ] Docker Compose runs the stack
- [ ] application is deployed to Ubuntu Server
- [ ] README documents setup and usage
- [ ] architecture is documented
- [ ] important technical decisions are documented

Stop adding CV-oriented features after this point unless explicitly requested.

---

# 13. First Task

Start with **Phase 0 and Phase 1 only**.

Before modifying code:

1. summarize the proposed project structure
2. explain which files you will create
3. explain any dependency choices

Then implement:

- backend skeleton
- FastAPI app
- `GET /api/health`
- pytest test
- `.gitignore`
- `.env.example`
- basic README instructions

Do not implement:
- Ollama
- OpenAI
- PostgreSQL
- embeddings
- RAG
- Docker
- frontend behavior

After implementation:

1. run tests
2. show the result
3. explain how to run the backend locally
4. stop and wait for the next task
