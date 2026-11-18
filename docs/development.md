# Development guide

Detailed setup, configuration, API behavior, and verification instructions for Context Mind.

[Back to the project overview](../README.md).

## Local setup

Requires Python 3.11+ and [Ollama](https://ollama.com/download). From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "./backend[dev]"
Copy-Item .env.example .env
```

On Linux/macOS, use `python3 -m venv .venv`, `source .venv/bin/activate`, and
`cp .env.example .env`; the remaining Python commands are the same.
Skip copying the environment file if you already have one.

Install and start Ollama, then download the default model:

```text
ollama pull llama3.2:3b
```

The Ollama desktop app usually starts its service automatically. If needed,
run `ollama serve` in another terminal. Pulling and running the model requires
disk space and RAM; choose a smaller or larger model to suit your machine.

The root `.env` accepts these settings. Blank values use the defaults shown here:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `Context Mind API` | API title |
| `LLM_PROVIDER` | `ollama` | Only supported provider in this phase |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama host |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model name; pull it with Ollama first |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Positive HTTP timeout in seconds |
| `DATABASE_URL` | unset | PostgreSQL connection URL; required only for indexing and migrations |
| `EMBEDDING_PROVIDER` | `local` | Local embedding inference through Ollama |
| `EMBEDDING_BASE_URL` | `http://localhost:11434` | Embedding host, configured separately from chat |
| `EMBEDDING_MODEL` | `nomic-embed-text:v1.5` | Installed embedding model |
| `EMBEDDING_DIMENSIONS` | `768` | Expected vector size, 1–2000; must match the model |
| `EMBEDDING_BATCH_SIZE` | `16` | New texts per model request, 1–128 |
| `EMBEDDING_TIMEOUT_SECONDS` | `120` | Positive HTTP operation timeout |

Environment variables override `.env`. Restart the backend after changing settings.
The timeout limits HTTP operations, including waiting for an answer; it is not a
total wall-clock deadline. The first answer may take longer while the model loads.
Ollama may run on another trusted LAN machine: set its reachable base URL and
restrict access to the trusted network. Do not expose Ollama to the public internet.
That machine must remain online while using chat.

Start the backend from the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

Open <http://127.0.0.1:8000/docs> for interactive API requests.

## Manual verification

Health works independently of Ollama:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType 'application/json' -Body '{"question":"Explain dependency injection."}'
```

Health returns `{"status":"ok"}`; chat returns `{"answer":"..."}`.
Each request sends one question and returns one complete answer. There is no
conversation history or repository context yet. No cloud API key is needed.

Invalid questions return **422** (missing, blank, non-string, or over 10,000 characters).
An unreachable Ollama host returns **503** with startup/configuration guidance.
A timeout returns **504**. Upstream HTTP errors, missing models, and unusable
responses return **502**; missing-model errors suggest checking and pulling the model.
Stop Ollama and repeat the chat request to verify the connection error, or set a
very short timeout and restart the backend to exercise timeout handling.

## Repository scanning (phase three)

Git must be installed and available on the backend machine's `PATH`. Keep the
backend bound to localhost while using this unauthenticated local-file endpoint.

In <http://127.0.0.1:8000/docs>, expand **POST /api/repositories/scan**, click
**Try it out**, and execute:

```json
{"path": "C:/path/to/repository"}
```

Use an absolute path to the root of an existing local Git working tree, containing
a `.git` directory or worktree marker file. The path is on the machine running
the backend. A repository subdirectory, a bare repository, or a remote URL is not
accepted. No commit is required, and the scanner does not modify the repository.

The response contains `repository_path`, `files`, and `skipped_files`. Each source
file looks like this:

```json
{
  "file_path": "src/example.py",
  "content": "print('hello')\n",
  "size_bytes": 15,
  "line_count": 1
}
```

Paths are relative to the repository and use forward slashes. Content is read
from the current working tree, including unstaged edits and untracked files.
Results are sorted by path. UTF-8 text is supported, including an optional BOM;
byte sizes refer to the original file, and empty files have zero lines.

Supported extensions: `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.json`, and `.md`.

The scanner uses `git ls-files` to honor Git's ignore rules for untracked files.
Tracked files remain candidates even if a later ignore rule matches them. Hard
exclusions still apply to tracked files: `.env` and `.env.*` (including examples),
private-key extensions, known credential and secret filenames, `.git`, generated
directories such as `node_modules`, `dist`, `build`, `coverage`, Python virtual
environments/caches, and credential directories such as `.ssh` and `.aws`.
Binary/non-UTF-8 files, files containing private-key markers, symlinks, Windows
junctions/reparse points, and unreadable files are also skipped.

`skipped_files` includes relative paths and reasons, never their contents. Files
omitted by Git's ignore rules are absent from both lists. Submodules are not
recursively scanned. Review the returned file list before using ingestion on a
new repository: these filters are not a comprehensive secret detector and cannot
recognize every password or token embedded in otherwise ordinary source files.
Only scan trusted local working trees that are not being modified concurrently.

Initial limits: files over **1 MiB** are skipped; more than **10 MiB** of accepted
source content or **20,000** candidate paths rejects the scan with **413**.
Invalid or inaccessible repositories return **400**, invalid request fields
return **422**, unavailable Git returns **503**, and Git commands exceeding
30 seconds return **504**.

To verify exclusions manually, create a disposable Git repository with `git init`,
add a source file and an `.env` containing dummy text, then scan it through `/docs`.
The source must appear in `files`; the `.env` contents must not appear anywhere.
For this project, confirm that environment files, `.git`, and `.venv` source files
are absent from `files`.

Scanning currently returns content only. It does not persist files, create chunks,
generate embeddings, or provide repository context to `/api/chat`. Ollama does
not need to be running for a scan.

## Source chunking (phase four)

Chunking splits accepted source files into smaller pieces so later retrieval can
select relevant sections instead of sending the whole repository to the model.
Each chunk keeps its file path and one-based, inclusive line references.

Restart the backend if necessary, open <http://127.0.0.1:8000/docs>, and use
**POST /api/repositories/chunks** -> **Try it out** with:

```json
{
  "path": "C:/path/to/repository",
  "chunking": {
    "max_lines": 80,
    "overlap_lines": 10
  }
}
```

The `chunking` object is optional; these are its defaults. `max_lines` must be an
integer from 1 to 500. `overlap_lines` must be an integer from 0 to 100 and smaller
than `max_lines`. Invalid options return **422**, before the repository is read.
When using a smaller window, lower the overlap too.

The endpoint runs the existing scanner first, applying all the same exclusions,
Git requirements, and scan limits. Its response contains `repository_path`, the
effective `chunking` options, `chunks`, and `skipped_files`. It returns chunk text
without duplicating the original full-file list. Each chunk has this shape:

```json
{
  "file_path": "src/example.py",
  "start_line": 1,
  "end_line": 2,
  "content": "def hello():\n    return 'hello'\n"
}
```

With defaults, a 160-line file produces ranges **1–80**, **71–150**, and
**141–160**. The overlap repeats ten lines to retain nearby context across
boundaries. A file of at most 80 lines produces one chunk; an empty file produces
none. Files are kept separate, line numbering restarts for each file, and output
order is deterministic. Source whitespace, line endings, and a missing final
newline are preserved. A UTF-8 BOM is already removed by the scanner.

To verify manually, compare a returned chunk's content with the indicated lines
in its source file. Use `max_lines: 5` and `overlap_lines: 1` to make overlapping
ranges easier to inspect. The next chunk should start on the previous chunk's
last line, unless that chunk already reached the end of the file.

The implementation uses line windows rather than syntax-aware parsing. Windows
may split functions or classes, and unusually long lines are kept intact: this is
a line limit, not a character or model-token limit. Overlap increases output size.
More than **20,000 chunks** or **20 MiB of chunk text** returns **413**, without a
partial result. These limits are in addition to the scanner's limits. Scanner
error statuses are preserved by this endpoint.

This endpoint returns chunks in memory only. Use the indexing endpoint below to
store them. Ollama is not required for chunking. Indexing calls the embedding service for new content.

## PostgreSQL persistence (phase five)

### Local database with Docker

With Docker Desktop running, use the database-only development setup from the
repository root. Set `POSTGRES_PASSWORD` in the private root `.env`, and set
`DATABASE_URL` to `postgresql+psycopg://context_mind:<URL-encoded-password>@localhost:5433/context_mind`.
The two settings must use the same password (the URL needs URL encoding).

```powershell
docker compose --project-name context-mind --env-file .env -f infra/compose.postgres.yml up -d --wait
```

This starts PostgreSQL 17 with pgvector and creates the `context_mind` database and login on the
first start. Port **5433** on localhost avoids common conflicts with databases on
5432; the container internally uses 5432. DBeaver connects to host `localhost`,
port `5433`, database `context_mind`, username `context_mind`, and your password.
FastAPI continues running directly on Windows. The application tables still need
the Alembic migration described below.

The named volume keeps database files after container replacement. Stop the
database with the same Compose options and `stop` instead of `up -d --wait`.
Starting it again uses the existing data. Changing `POSTGRES_PASSWORD` after the
volume is initialized does not change the existing database role's password.
Never add real credentials to `.env.example` or commit `.env`.

### Native PostgreSQL alternative

Install PostgreSQL locally using its native installer/package manager and start
the service. Also install pgvector for your PostgreSQL major version.
In `psql` as a database administrator, create a dedicated login and
database (the password prompt avoids embedding a password in SQL history):

```sql
CREATE ROLE context_mind LOGIN;
\password context_mind
CREATE DATABASE context_mind OWNER context_mind;
```

Connect to `context_mind` as the administrator and execute
`CREATE EXTENSION IF NOT EXISTS vector;` before running migrations as the
application login. The Docker development login already has the required
privileges; a native limited login usually does not.

Set `DATABASE_URL` in your root `.env` to a connection URL with your own credentials:

```text
postgresql+psycopg://context_mind:<URL-encoded-password>@localhost:5432/context_mind
```

URL-encode special characters in the username/password. Keep the real URL private.
Install the updated dependencies and run the migration from the repository root,
with the virtual environment activated:

```powershell
python -m pip install -e "./backend[dev]"
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m uvicorn app.main:app --app-dir backend --reload
```

Alembic tracks schema revisions in the database; `upgrade head` applies pending
changes. Tables are not created automatically when the API starts. The first
migration creates `repositories` and `code_chunks`, with a foreign key and cascading
chunk deletion. Migration rollback (`downgrade base`) deletes these tables and
their stored data; use it only on disposable databases or after a backup.

In `/docs`, execute **POST /api/repositories/index** using the same body as chunking:

```json
{
  "path": "C:/path/to/repository",
  "chunking": {"max_lines": 80, "overlap_lines": 10}
}
```

The endpoint scans and chunks before opening its write transaction. It returns a
repository summary (`id`, `name`, `path`, UTC `indexed_at`, `chunk_count`) and
`skipped_files`. Stored chunks include exact source text, file path, inclusive line
references, repository ID, and a SHA-256 hash of their UTF-8 content.

The scanner's canonical absolute path identifies a repository. Re-indexing that
path keeps its repository ID and atomically replaces all chunks, including removing
chunks for deleted or newly excluded files. An empty repository clears its chunks.
If saving fails, the previous snapshot survives. Concurrent updates to an existing
repository serialize through a row lock; conflicting first inserts return **409**
and can be retried. Overlapping scans are not ordered by source modification time;
index each repository sequentially for predictable snapshots. Chunk IDs may change
on re-indexing; phase six reuses matching vectors before replacing chunk rows.

Without `DATABASE_URL`, indexing returns **503** with setup guidance. Unreachable
PostgreSQL or missing migrations also return **503**, without exposing database
exceptions or source text. Scan/chunk validation and error statuses still apply.
Health, scanning, chunking, and chat do not require a working database connection.
Health remains a basic application check, not a database readiness check.

To verify persistence, index a disposable repository, restart the backend, and
inspect the database using `psql` or pgAdmin:

```sql
SELECT id, name, path, indexed_at FROM repositories;
SELECT repository_id, file_path, start_line, end_line, content_hash
FROM code_chunks ORDER BY repository_id, file_path, start_line;
```

Edit/delete a source file and index the same path again. Confirm the repository ID
stays the same, the timestamp updates, and its chunks reflect the new files.
The scan and chunk endpoints remain previews. Stored chunks are not yet used by
chat. Phase six below adds pgvector and embedding generation to this endpoint.

## Local embeddings (phase six)

An embedding is a numeric representation of a chunk's meaning. PostgreSQL stores
these vectors using pgvector so phase seven can compare them with a question's
vector. Phase six generates and stores vectors; phase seven below adds retrieval.
Repository context for chat comes in phase eight.

The provider interface is independent of Ollama. Its first implementation calls
local Ollama using HTTPX instead of loading a Python ML framework in the backend.
No cloud embedding service or API key is required. The model download needs
internet access; source text is sent only to the configured embedding host.
Leave it at localhost or explicitly configure a trusted LAN host. HTTP proxy
environment variables are ignored by this client.

With the virtual environment activated, run from the repository root:

```powershell
python -m pip install -e "./backend[dev]"
ollama pull nomic-embed-text:v1.5
docker compose --project-name context-mind --env-file .env -f infra/compose.postgres.yml up -d --wait
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
```

The current revision should be **0002**. The Compose image includes pgvector while
retaining PostgreSQL major version 17, port 5433, and the existing named volume.
Do not delete the volume when updating the image. Migration 0002 enables pgvector
and adds nullable `embedding`, `embedding_model`, and `embedding_key` columns.
Existing chunks survive and acquire vectors on their next index run. Downgrading
to 0001 removes these columns and their vectors while keeping source chunks and
the shared extension.

Restart FastAPI and execute **POST /api/repositories/index** in `/docs`:

```json
{
  "path": "C:/path/to/repository",
  "chunking": {"max_lines": 40, "overlap_lines": 5}
}
```

The response adds `embedding_model`, `embedded_chunk_count`, and
`reused_chunk_count`. These counts describe final chunks: identical new texts
share one model inference even when they count as multiple embedded chunks.

The first run embeds new content in batches. Nomic inputs receive its recommended
`search_document: ` prefix; stored content stays unchanged. A second unchanged run
should report zero embedded chunks and all chunks reused. Reuse is scoped to the
repository and matches content/hash plus model tag, host, dimensions, prefix, and
provider implementation version. Moved unchanged text can reuse a vector. Changing
the model, host, or dimensions regenerates vectors. Use a new model tag when
replacing weights: changing weights behind the same tag is not detected.

The database `vector` column permits different dimensions; response validation
enforces the configured dimension for each run. `embedding_key` identifies the
vector space, which retrieval filters by. No similarity index is added
in this phase.

Verify in DBeaver or `psql`:

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT file_path, start_line, end_line, embedding_model,
       vector_dims(embedding) AS dimensions
FROM code_chunks ORDER BY repository_id, file_path, start_line;
```

The default model produces **768** dimensions. Edit a file and index again: only
changed chunk contents should need embedding. Deleted/newly excluded files are
removed. Empty repositories clear chunks without calling the model. Scan and
chunk endpoints remain previews without embedding inference.

Inference finishes before the database write transaction. Failed batches leave
the previous snapshot and timestamp untouched. Vectors must have matching
counts/dimensions, finite float32-compatible numbers, and nonzero values. An
unavailable model service returns **503**, timeouts **504**, and model/response
failures **502**, without echoing source code or upstream error bodies.

Input truncation is disabled. Line windows are not token limits: reduce
`chunking.max_lines` and overlap if input exceeds the model context. An unusually
long single line may require a different model or future chunking improvements.
An entire index is one synchronous request, so large repositories can take time.
Keep indexing sequential for each repository.

Provider details: [Ollama batch embedding API](https://docs.ollama.com/api/embed),
[Nomic document-prefix guidance](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5),
and [pgvector installation](https://github.com/pgvector/pgvector#docker).

## Semantic retrieval (phase seven)

Semantic search embeds a question and asks pgvector to rank chunks from one
indexed repository by cosine distance. A smaller distance means a closer vector
direction; the response reports `similarity = 1 - distance`, from -1 to 1, with
higher values first. This is a relevance signal, not a probability of correctness.

No new dependency or migration is required. With PostgreSQL and Ollama running,
restart the backend and open <http://127.0.0.1:8000/docs>:

1. Index a repository with **POST /api/repositories/index** and copy its `id`.
2. Execute **POST /api/repositories/{repository_id}/search** with that ID and:

   ```json
   {"question": "How are unsafe source files excluded?", "top_k": 3}
   ```

3. Inspect `matches`: each contains exact chunk `content`, `file_path`,
   `start_line`, `end_line`, and `similarity`. Compare the references with the
   indexed source snapshot. Matches are ordered by descending similarity, then
   file path, start line, and chunk ID to break ties.
4. Omit `top_k` to use `RETRIEVAL_TOP_K` (default **5**). Both the setting and the
   request allow **1-20**. The question is trimmed and must contain **1-8000**
   characters. Invalid requests return **422**.

The response also includes `repository_id`, the trimmed `question`, and effective
`top_k`. An empty indexed repository returns `matches: []` without model inference;
fewer stored chunks produce fewer matches. Unknown repository IDs return **404**.
The chat model is not called during search.

The provider has separate document and question embedding operations. Nomic uses
`search_document: ` for source and `search_query: ` for questions; other models
receive raw text. Query embeddings use the existing document vector-space identity,
so phase-six embeddings remain reusable. Search checks the whole snapshot's
model and embedding key before inference and filters the SQL query by the same
identity. A model, host, dimensions, or prefix change requires re-indexing; legacy
or incompatible snapshots return **409** with that instruction. A shared repository
row lock keeps a concurrent index from replacing chunks during the search.

Missing database configuration and database failures return **503**. Embedding
connection failures return **503**, timeouts **504**, and invalid vectors or model
responses **502**. Stop Ollama and search a nonempty compatible repository to
check connection handling. Changing `EMBEDDING_MODEL`, restarting, and searching
before re-indexing should return **409**; restore the original setting afterward.

Search uses exact pgvector cosine distance with a SQL limit. No approximate vector
index or reranking is needed for this MVP phase; exact search may become slower
as repositories grow. There is no score threshold, so an unrelated question can
still return the closest chunks. Results describe the last indexed snapshot and
may repeat overlapping source lines. Answer generation and insufficient-context
handling belong to phase eight; retrieval quality evaluation belongs to phase nine.

## Tests

With the virtual environment activated, run from the repository root:

```powershell
Set-Location backend
python -m pytest -q
```

Tests use HTTPX's mock transport to check the actual Ollama request format,
answer handling, validation, connection errors, timeouts, and malformed responses.
They require neither a running Ollama service nor a downloaded model. The manual
chat check above verifies the full path through a real local model.

Repository tests create temporary Git repositories and check supported files,
working-tree edits, nested ignore rules, tracked secret exclusions, binary data,
metadata, size limits, invalid paths, and Git failures. Link tests may be skipped
on Windows if creating symlinks is not permitted. Git is required for these tests.

Chunking tests verify complete line coverage, overlap, exact source references,
file boundaries, empty files, newline/Unicode preservation, request validation,
output limits, and the scan-to-chunks endpoint with exclusions applied.

Persistence tests execute the migration chain's upgrade/downgrade against an
in-memory SQLite test database, then check stored metadata and hashes, new-session
reads, replacement, rollback after a failed insert, repository isolation, cascading
deletion, scanner exclusions, and safe database errors. SQLite is only a test
fixture; application configuration accepts PostgreSQL only. These tests do not
prove PostgreSQL connectivity or row-lock behavior: use the manual PostgreSQL
verification above on a configured local server.

Embedding unit tests cover batching, deduplication, unchanged-content reuse,
configuration changes, legacy chunks, malformed vectors, transport errors, and
failure rollback. They use HTTPX mock transport and the SQLite test fixture; no
live model is required. SQLite represents vectors as JSON only for these tests.

To run the opt-in test against configured local PostgreSQL/pgvector and Ollama,
after running migrations and downloading the model, use from `backend`:

```powershell
$env:RUN_LOCAL_EMBEDDING_INTEGRATION = "1"
python -m pytest -q tests/test_embedding_integration.py
Remove-Item Env:RUN_LOCAL_EMBEDDING_INTEGRATION
```

The first test indexes a disposable Git repository, checks real question embedding,
search and source references, vector storage and reuse, failure rollback, and edits
and deletion. The second uses known vectors in real PostgreSQL to verify cosine
ranking, top-k limits, scores, and isolation from other repositories and dimensions.
Both remove only their own temporary repository records.

Retrieval unit tests check query prefixes, unchanged embedding identity, request
validation, defaults and overrides, missing/empty/incompatible snapshots, invalid
query vectors, source mapping, safe error statuses, and PostgreSQL query compilation.
They do not emulate pgvector ranking in SQLite; ranking is checked by the opt-in
PostgreSQL test above.
