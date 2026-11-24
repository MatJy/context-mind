"""Validate gold evidence, scoring failures, and report orchestration offline."""

import asyncio
import importlib.util
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation import __main__ as runner
from app.evaluation.scoring import evidence_recall, load_cases, score_answer
from app.models import Repository
from app.schemas.rag import RAGResponse, SourceReference
from app.schemas.retrieval import RetrievalMatch


def cases():
    return load_cases(runner.DATA / "cases.json").cases


def response(answer: str, paths: tuple[str, ...] = ("shipping.py",)) -> RAGResponse:
    return RAGResponse(repository_id=1, answer=answer, sources=[
        SourceReference(source_id=index, file_path=path, start_line=1, end_line=10)
        for index, path in enumerate(paths, 1)
    ])


def test_gold_corpus_and_line_references_are_fixed() -> None:
    suite = cases()
    assert {case.kind for case in suite} == {"direct", "multiple_files", "unanswerable"}
    assert len({case.id for case in suite}) == len(suite)
    for case in suite:
        assert bool(case.evidence) == (case.kind != "unanswerable")
        for span in case.evidence:
            source = (runner.DATA / "repository" / span.file_path).read_text(encoding="utf-8")
            assert 1 <= span.start_line <= span.end_line <= len(source.splitlines())
    assert len({span.file_path for span in suite[1].evidence}) == 2


def test_known_repository_behavior(monkeypatch) -> None:
    root = runner.DATA / "repository"
    modules = {}
    for name in ("shipping", "orders"):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    assert modules["shipping"].shipping_fee(49) == 5
    assert modules["shipping"].shipping_fee(50) == 0
    assert modules["orders"].order_total(40) == 45


def test_retrieval_and_generation_failures_are_separate() -> None:
    case = cases()[1]
    answer = response("order_total adds shipping_fee; the result is 45 [1] [2].", ("shipping.py", "orders.py"))
    assert evidence_recall(case.evidence, answer.sources[:1]) == 0.5
    assert evidence_recall(case.evidence, answer.sources) == 1.0
    score = score_answer(case, answer)
    assert score["answer_quality"]["automatic_pass"]
    assert score["hallucination"]["automatic_pass"]
    assert score["manual_review_required"]


def test_retrieval_requires_the_full_expected_span() -> None:
    case = cases()[0]
    answer = response("answer")
    answer.sources[0].end_line = 5
    assert evidence_recall(case.evidence, answer.sources) == 0.0
    assert evidence_recall(case.evidence, []) == 0.0
    assert evidence_recall([], answer.sources) is None


def test_missing_facts_and_citations_are_flagged() -> None:
    case = cases()[0]
    good = score_answer(case, response("Shipping is free at 50; below it the fee is 5 [1]."))
    assert good["answer_quality"]["automatic_pass"]
    missing_citation = score_answer(case, response("Shipping is free at 50; below it the fee is 5."))
    assert not missing_citation["answer_quality"]["automatic_pass"]
    assert not missing_citation["answer_quality"]["citation_present"]
    missing_fact = score_answer(case, response("Free shipping starts at 50 [1]."))
    assert missing_fact["answer_quality"]["missing_fact_patterns"] == [r"\b5\b"]


def test_multi_file_answer_requires_both_citations() -> None:
    case = cases()[1]
    score = score_answer(case, response("order_total adds shipping_fee: 45 [1].", ("shipping.py", "orders.py")))
    assert not score["answer_quality"]["automatic_pass"]
    assert score["answer_quality"]["cited_evidence_recall"] == 0.5


def test_subtotal_is_not_mistaken_for_a_wrong_total() -> None:
    case = cases()[1]
    score = score_answer(case, response(
        "order_total adds shipping_fee; a subtotal of 40 produces 45 [1] [2].",
        ("shipping.py", "orders.py"),
    ))
    assert score["hallucination"]["automatic_pass"]
    wrong = score_answer(case, response("The total is 40 [1]."))
    assert not wrong["hallucination"]["automatic_pass"]


def test_arithmetic_and_grouped_citations_are_recognized() -> None:
    case = cases()[1]
    score = score_answer(case, response(
        "order_total adds shipping_fee; subtotal 40 produces a total of 40 + 5 = 45 [1, 2].",
        ("shipping.py", "orders.py"),
    ))
    assert score["answer_quality"]["automatic_pass"]
    assert score["hallucination"]["automatic_pass"]
    unknown = score_answer(case, response("order_total shipping_fee 45 [1, 9]."))
    assert unknown["hallucination"]["unknown_citation_ids"] == [9]


def test_unspecified_currency_is_an_unsupported_assumption() -> None:
    score = score_answer(cases()[0], response("Shipping is free at $50, otherwise $5 [1]."))
    assert score["answer_quality"]["automatic_pass"]
    assert not score["hallucination"]["automatic_pass"]


def test_invented_citations_files_and_wrong_assertions() -> None:
    score = score_answer(cases()[0], response("The threshold is 100, using missing.py [9]."))
    assert not score["hallucination"]["automatic_pass"]
    assert score["hallucination"]["unknown_citation_ids"] == [9]
    assert score["hallucination"]["unknown_file_paths"] == ["missing.py"]
    assert score["hallucination"]["forbidden_assertion_patterns"]


def test_absent_answer_requires_refusal_even_with_irrelevant_sources() -> None:
    case = cases()[2]
    good = score_answer(case, response("The repository context is insufficient to determine payment storage."))
    assert good["answer_quality"]["automatic_pass"]
    assert good["hallucination"]["automatic_pass"]
    bad = score_answer(case, response("It uses PostgreSQL and is encrypted using AES [1]."))
    assert not bad["answer_quality"]["automatic_pass"]
    assert not bad["hallucination"]["automatic_pass"]
    # A refusal phrase cannot hide a configured forbidden assertion.
    contradictory = score_answer(case, response("Context is insufficient, but it uses PostgreSQL."))
    assert not contradictory["hallucination"]["automatic_pass"]


@pytest.mark.parametrize("fail_generation", [False, True])
def test_runner_records_two_context_modes_and_cleans_up(database, monkeypatch, fail_generation) -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, database_url="postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setattr(runner, "Settings", lambda: settings)
    monkeypatch.setattr(runner, "create_engine", lambda *args, **kwargs: database)
    # Production owns its engine; the fixture must retain its SQLite connection
    # for verification and migration teardown after evaluate() disposes it.
    monkeypatch.setattr(database, "dispose", MagicMock())
    repository_id = 0

    def index(session, path, chunks, provider, batch_size):
        nonlocal repository_id
        from app.services.persistence import persist_repository
        repo = persist_repository(session, path, chunks)
        repository_id = repo.id
        return SimpleNamespace(repository=repo)

    monkeypatch.setattr(runner, "index_repository", index)
    matches = [RetrievalMatch(
        file_path="shipping.py", content="source", start_line=1, end_line=10, similarity=0.9,
    )]
    monkeypatch.setattr(runner, "retrieve_chunks", MagicMock(return_value=matches))

    async def generate(repo_id, question, context, provider, budget):
        assert context  # Unknown question must test refusal with nonempty context.
        if fail_generation:
            raise RuntimeError("private failure")
        return RAGResponse(repository_id=repo_id, answer="insufficient context", sources=[
            SourceReference(source_id=i, file_path=m.file_path, start_line=m.start_line, end_line=m.end_line)
            for i, m in enumerate(context, 1)
        ])

    generate_mock = AsyncMock(side_effect=generate)
    monkeypatch.setattr(runner, "generate_answer", generate_mock)
    if fail_generation:
        with pytest.raises(RuntimeError, match="private failure"):
            asyncio.run(runner.evaluate(2))
    else:
        report = asyncio.run(runner.evaluate(2))
        assert len(report["cases"]) == 3
        assert generate_mock.await_count == 6
        assert report["cases"][1]["retrieval"]["evidence_recall_at_k"] == 0.5
        assert report["cases"][1]["oracle_context"]["prompt_evidence_recall"] == 1.0
        assert report["cases"][2]["retrieval"]["evidence_recall_at_k"] is None
        assert report["configuration"]["top_k"] == 2
        assert "test:test" not in json.dumps(report)
    assert repository_id > 0
    with Session(database) as session:
        assert session.scalar(select(Repository).where(Repository.id == repository_id)) is None


def test_cli_suppresses_private_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["evaluation"])
    monkeypatch.setattr(runner, "evaluate", AsyncMock(side_effect=RuntimeError("private credentials")))
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 1
    assert "private credentials" not in capsys.readouterr().err
