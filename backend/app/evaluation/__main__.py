"""Run with python -m app.evaluation from backend; requires local services."""

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import httpx
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.evaluation.scoring import evidence_recall, load_cases, score_answer
from app.models import Repository
from app.schemas.chunk import ChunkingOptions
from app.schemas.retrieval import RetrievalMatch
from app.services.chunking import chunk_files
from app.services.indexing import index_repository
from app.services.local_embeddings import LocalEmbeddingProvider
from app.services.ollama import OllamaProvider
from app.services.rag import generate_answer
from app.services.repository import scan_repository
from app.services.retrieval import retrieve_chunks

DATA = Path(__file__).resolve().parents[2] / "evaluation"


async def evaluate(top_k: int) -> dict[str, object]:
    settings = Settings()
    if settings.database_url is None:
        raise ValueError("Configure DATABASE_URL and apply migrations before evaluation.")
    cases = load_cases(DATA / "cases.json")
    options = ChunkingOptions(max_lines=40, overlap_lines=5)
    corpus_hash = sha256()
    for path in sorted((DATA / "repository").glob("*.py")):
        corpus_hash.update(path.name.encode())
        corpus_hash.update(path.read_bytes())
    engine = create_engine(
        settings.database_url.get_secret_value(), connect_args={"connect_timeout": 5},
    )
    rows = []
    repository_id = None
    try:
        with tempfile.TemporaryDirectory(prefix="context-mind-evaluation-") as directory:
            root = Path(directory) / "shop"
            shutil.copytree(DATA / "repository", root)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True, timeout=30)
            chunks = chunk_files(scan_repository(str(root)).files, options)
            async with AsyncExitStack() as stack:
                embedding_client = stack.enter_context(httpx.Client(
                    base_url=str(settings.embedding_base_url),
                    timeout=settings.embedding_timeout_seconds, trust_env=False,
                ))
                llm_client = await stack.enter_async_context(httpx.AsyncClient(
                    base_url=str(settings.ollama_base_url), timeout=settings.ollama_timeout_seconds,
                ))
                session = stack.enter_context(Session(engine, expire_on_commit=False))
                embeddings = LocalEmbeddingProvider(
                    embedding_client, settings.embedding_model, settings.embedding_dimensions,
                )
                llm = OllamaProvider(llm_client, settings.ollama_model)
                indexed = index_repository(
                    session, str(root.resolve()), chunks, embeddings, settings.embedding_batch_size,
                )
                repository_id = indexed.repository.id
                for case in cases.cases:
                    with session.begin():
                        matches = retrieve_chunks(session, repository_id, case.question, embeddings, top_k)
                    # Oracle context isolates generation from retrieval errors. For
                    # absent answers, use real but irrelevant code, not empty input.
                    oracle = [
                        RetrievalMatch(**chunk.model_dump(), similarity=1.0)
                        for chunk in chunks
                        if not case.evidence or any(
                            chunk.file_path == span.file_path for span in case.evidence
                        )
                    ]
                    answers = {}
                    for name, context in (("retrieved_context", matches), ("oracle_context", oracle)):
                        response = await generate_answer(
                            repository_id, case.question, context, llm, settings.rag_max_context_characters,
                        )
                        answers[name] = {
                            "answer": response.answer,
                            "sources": [source.model_dump() for source in response.sources],
                            "prompt_evidence_recall": evidence_recall(case.evidence, response.sources),
                            **score_answer(case, response),
                        }
                    rows.append({
                        "id": case.id, "kind": case.kind, "question": case.question,
                        "expected_evidence": [span.model_dump() for span in case.evidence],
                        "retrieval": {
                            "evidence_recall_at_k": evidence_recall(case.evidence, matches),
                            "matches": [match.model_dump() for match in matches],
                        },
                        **answers,
                    })
    finally:
        try:
            if repository_id is not None:
                with engine.begin() as connection:
                    connection.execute(delete(Repository).where(Repository.id == repository_id))
        finally:
            engine.dispose()
    return {
        "evaluation_version": cases.version,
        "case_set_sha256": sha256((DATA / "cases.json").read_bytes()).hexdigest(),
        "corpus_sha256": corpus_hash.hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "llm_model": settings.ollama_model, "top_k": top_k,
            "chunking": options.model_dump(),
            "max_context_characters": settings.rag_max_context_characters,
        },
        "manual_review_required": True, "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, choices=range(1, 21), default=2)
    parser.add_argument("--output", type=Path, help="Write a JSON report; otherwise print to stdout")
    arguments = parser.parse_args()
    try:
        report = asyncio.run(evaluate(arguments.top_k))
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if arguments.output:
            arguments.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except Exception as exc:
        # Database and HTTP errors may include private URLs. Never print raw errors.
        parser.exit(1, f"Evaluation failed ({type(exc).__name__}). Check DATABASE_URL, migrations, "
                    "Git, Ollama models, and output permissions. "
                    "No new quality report was produced.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
