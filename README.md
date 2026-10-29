# Context Mind

Local-first AI codebase assistant. Give it your repos, and let the AI help you.

Phases 0–2 are implemented: a FastAPI backend with health and single-question
local Ollama chat. Repository ingestion and RAG come in later phases.

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
