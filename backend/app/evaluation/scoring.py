"""Deterministic evidence and text checks, not a semantic correctness judge."""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.rag import RAGResponse, SourceReference
from app.schemas.retrieval import RetrievalMatch


class Evidence(BaseModel):
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class EvaluationCase(BaseModel):
    id: str
    kind: Literal["direct", "multiple_files", "unanswerable"]
    question: str
    evidence: list[Evidence]
    fact_patterns: list[str]
    forbidden_patterns: list[str]


class EvaluationSet(BaseModel):
    version: Literal[1]
    cases: list[EvaluationCase]


def load_cases(path: Path) -> EvaluationSet:
    return EvaluationSet.model_validate_json(path.read_text(encoding="utf-8"))


def evidence_recall(
    expected: list[Evidence], actual: list[RetrievalMatch] | list[SourceReference],
) -> float | None:
    """Fraction of required spans fully present; absent answers have no gold spans."""
    if not expected:
        return None
    covered = sum(
        any(
            source.file_path == span.file_path
            and source.start_line <= span.start_line and source.end_line >= span.end_line
            for source in actual
        )
        for span in expected
    )
    return covered / len(expected)


def score_answer(case: EvaluationCase, response: RAGResponse) -> dict[str, object]:
    """Keep missing facts separate from signals of unsupported assertions."""
    answer = response.answer
    missing = [pattern for pattern in case.fact_patterns if not re.search(pattern, answer, re.I)]
    forbidden = [pattern for pattern in case.forbidden_patterns if re.search(pattern, answer, re.I)]
    citation_groups = re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer)
    cited = {int(value.strip()) for group in citation_groups for value in group.split(",")}
    supplied = {source.source_id for source in response.sources}
    unknown = sorted(cited - supplied)
    # Match common code/document paths, including bare file names. This is a
    # diagnostic heuristic, not a parser for all possible citation formats.
    paths = set(re.findall(r"[\w./-]+\.(?:py|tsx?|jsx?|md|json)\b", answer))
    unknown_paths = sorted(paths - {source.file_path for source in response.sources})
    refusal = bool(re.search(
        r"insufficient|not (?:provided|implemented|available|specified|present|shown|defined)|"
        r"no (?:information|evidence|database|payment)|cannot (?:determine|answer)|"
        r"does not (?:contain|include|specify|implement)", answer, re.I,
    ))
    citation_present = bool(cited & supplied)
    # Require a citation for every expected evidence span, not just one citation
    # somewhere in a multi-file answer.
    cited_sources = [source for source in response.sources if source.source_id in cited]
    cited_recall = evidence_recall(case.evidence, cited_sources)
    quality_pass = (
        refusal if case.kind == "unanswerable"
        else not missing and citation_present and cited_recall == 1.0
    )
    hallucination_pass = not forbidden and not unknown and not unknown_paths
    if case.kind == "unanswerable":
        hallucination_pass = hallucination_pass and refusal
    return {
        "answer_quality": {
            "automatic_pass": quality_pass, "missing_fact_patterns": missing,
            "citation_present": citation_present, "cited_evidence_recall": cited_recall,
        },
        "hallucination": {
            "automatic_pass": hallucination_pass, "refusal_detected": refusal,
            "forbidden_assertion_patterns": forbidden, "unknown_citation_ids": unknown,
            "unknown_file_paths": unknown_paths,
        },
        "manual_review_required": True,
    }
