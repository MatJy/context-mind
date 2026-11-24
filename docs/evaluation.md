# Evaluation (phase nine)

This evaluation separates retrieval coverage, answer quality, and hallucination
signals. The fixed [shop repository](../backend/evaluation/repository/) and
[question set](../backend/evaluation/cases.json) make inputs and expected evidence
repeatable. Live model output remains variable: these checks do not certify that
an answer is true.

| Case | Required evidence | Expected behavior |
| --- | --- | --- |
| `shipping_threshold` | `shipping.py:3-10` | Free shipping at subtotal 50 or above; fee 5 below it, with a citation. |
| `order_total` | `orders.py:3-7` and `shipping.py:3-10` | Explain adding `shipping_fee` to the subtotal; subtotal 40 produces 45; cite both files. |
| `absent_payment_storage` | None: no payment persistence or encryption exists | State that repository context is insufficient; do not invent a database or encryption scheme. |

The corpus also includes an irrelevant catalog file. Tests verify gold line
ranges against real files and execute the fixture's shipping and total functions.
Do not edit the corpus without reviewing the question set and its expected spans.

## Run the evaluator

Use the source checkout, with the existing backend development environment,
PostgreSQL/pgvector migrations applied, and both configured Ollama models ready.
The runner reads the normal root `.env`; it does not need the API server running.
No new dependencies or migrations are required.

From the repository root, with the virtual environment activated:

```powershell
Set-Location backend
New-Item -ItemType Directory -Force evaluation/results | Out-Null
python -m app.evaluation --top-k 2 --output evaluation/results/local.json
```

For Linux/macOS, use `mkdir -p evaluation/results` in place of `New-Item`.
Omit `--output` to print JSON. `--top-k` accepts 1-20 and defaults to 2, deliberately
below the corpus's file count. Run again with 1 or 3 to inspect sensitivity to
retrieval breadth. Do not compare different settings as if they were the same run.

The runner copies the fixture to a temporary Git repository, scans and chunks it
with `max_lines=40` and `overlap_lines=5`, and indexes it using real local embeddings.
Each question runs real pgvector retrieval, then two generations through the
production RAG prompt builder and LLM provider:

- `retrieved_context`: the actual top-k matches, measuring the full pipeline.
- `oracle_context`: known relevant source files, isolating generation from search
  misses. The unanswerable case receives all fixture code, so refusal is tested
  with nonempty, irrelevant context rather than the backend's empty-context fallback.

The run makes six chat generations and uses the normal model timeout. It removes
only its own temporary repository record afterward, including when generation
fails. Abrupt process termination or database failure during cleanup can leave an
evaluation record behind. Existing indexed repositories are not re-indexed.

Reports include raw answers, retrieved text, scores, prompt source references,
model names, dimensions, top-k, context budget, chunk options, corpus and question
hashes, and a UTC timestamp. Credentials and service URLs are excluded. Reports
are ignored by Git under `backend/evaluation/results/`. Model output is untrusted;
inspect it before sharing. Pin model weights/tags when comparing runs; a model
name alone does not identify immutable weights.

Exit status **0** means the run completed, including runs with failed quality
checks. Status **1** means setup, inference, cleanup, or report writing failed;
no new report should be interpreted as a completed run. Model-quality outcomes
are reported separately from execution status. A pre-existing output file is not
replaced when evaluation fails before report writing.

## Read the report

1. Inspect `retrieval.evidence_recall_at_k`. For answerable cases, this is the
   fraction of required file/line spans fully covered by retrieved chunks: 0,
   0.5, or 1 for the two-file case. For the absent answer it is `null`, since
   there is no relevant evidence to recover. Retrieving something for an absent
   answer is expected from top-k search without a relevance threshold.
2. Compare `prompt_evidence_recall` with retrieval recall. A lower value means
   the context budget discarded relevant chunks before generation.
3. Inspect each mode's `answer_quality`: required fact patterns, presence of
   inline numeric citations (`[1]` or grouped `[1, 2]`), and coverage of gold spans by cited sources.
   An answerable case passes only if all facts and all expected citations appear.
   The absent-answer case instead requires a recognized refusal.
4. Inspect `hallucination`: unknown citation IDs, mentioned code/document paths
   absent from the supplied context, selected known-wrong assertions, unsupported
   currency assumptions (the fixture specifies no currency), and refusal on the
   absent question. This pass flag is independent of the answer-quality flag.
5. Read every raw answer against the source before accepting it. Every result
   carries `manual_review_required: true`.

Use this rubric for each context mode; record the review with the report:

| Dimension | Pass criteria | Failure examples |
| --- | --- | --- |
| Answer quality | All requested facts are correct, complete, and supported by cited spans | Wrong arithmetic, missing fee, missing inline citations, contradiction |
| Hallucination | No unsupported behavior, files, functions, database, or encryption claims | Invented storage implementation; a refusal followed by a guess |
| Citation support | Each substantive claim is supported by the actual cited lines | Real source ID attached to an unrelated claim |
| Absent answer | Clearly says the evidence does not establish an answer, without guessing | Confidently names PostgreSQL or AES without evidence |

If retrieved-context quality fails but oracle-context quality passes, inspect
retrieval coverage and context budget first. If both fail despite full evidence,
inspect model behavior and prompt compliance. Never infer that a correct citation
ID proves the claim is supported.

## Known limitations and baseline observations

### Local baseline: 2026-11-23

A live run completed at **11:46:26 UTC** using `nomic-embed-text:v1.5` (768
dimensions), `qwen2.5-coder:7b`, top-k 2, and the default 24000-character context
budget. The raw local report is generated at `backend/evaluation/results/local.json`.
The run used corpus SHA-256
`eee861a175b881611f331bd9244a2e57d2342808bbee1ab6b90ea004d6484583`
and case-set SHA-256
`9d5f38ccf027c4b6bebef1212891934158aebdc153083bd51dd5e75cf99f9931`.

| Case | Retrieval evidence recall | Retrieved: answer / hallucination checks | Oracle: answer / hallucination checks |
| --- | --- | --- | --- |
| Shipping threshold | 1.0 | Pass / Fail | Pass / Fail |
| Order total | 1.0 | Fail / Pass | Pass / Pass |
| Absent payment storage | Not applicable | Pass / Pass | Pass / Pass |

Manual review of all six answers confirmed the following:

- Both shipping answers gave the correct threshold and fee but introduced dollar
  currency, which is not specified by the code. Numeric answer checks passed;
  the unsupported-currency check correctly failed. These are not fully grounded
  answers despite the correct numbers.
- The retrieved-context order answer correctly calculated 45, but cited only
  `orders.py` while using fee/threshold facts from `shipping.py`. Its answer-quality
  check correctly failed for incomplete evidence citations. The oracle answer
  cited both source IDs and gave the supported calculation.
- Both absent-answer generations explicitly acknowledged insufficient context
  without naming an invented storage or encryption implementation.

An earlier run exposed scoring false positives for “subtotal of 40” and “total
of 40 + 5 = 45.” Word boundaries and arithmetic exclusions now prevent those
specific mistakes, with regression tests. Grouped citations such as `[1, 2]`
are also recognized. All reported baseline scores above come from a fresh live
run after those corrections. These observations do not justify a broader claim
about model quality; further questions and repeated runs are needed.

### Remaining limitations

The Phase 8 manual run against Context Mind returned documentation rather than
implementation files, described chunks as both non-overlapping and overlapping,
and omitted inline citations. Those observations motivate separate retrieval and
generation checks. They are not scores for this fixed shop corpus. The current
rubric catches missing citations; contradictions still require human review.

- Regex fact checks can accept a negated or contradictory statement and reject
  a correct paraphrase. They detect selected mistakes, not all wrong facts.
- Refusal detection can misread negation or accept a refusal followed by a guess.
  Configured forbidden assertions catch only a few such combinations.
- File-path and numeric bracket citation recognition is heuristic. Alternative citation
  syntax, bare file names instead of full paths, and prose punctuation may need
  manual interpretation. Valid IDs do not establish semantic entailment.
- Span recall requires a whole span in one chunk. It does not merge fragmented
  chunks, measure rank within top-k, or measure precision. Overlapping chunks
  and repeated source files can reduce useful context.
- Three small questions cannot represent large repositories, documentation-heavy
  indexes, prompt injection resilience, different languages, or every absent answer.
- Oracle context is a diagnostic baseline, not a fair replacement for retrieved
  context in reported end-to-end results. Do not combine the two scores.
- Offline unit tests prove scorer and runner behavior with controlled data;
  they do not measure real embedding or LLM quality. Live runs are observations,
  not deterministic tests with guaranteed identical answers.

## Offline verification

From `backend`, run `python -m pytest -q tests/test_evaluation.py` for the fixed
corpus, scoring counterexamples, report modes, safe errors, and cleanup tests.
Run `python -m pytest -q` for the complete backend suite. No live services are
needed by these tests. Phase ten (frontend) is outside this change.
