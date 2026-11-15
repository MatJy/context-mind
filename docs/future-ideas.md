# Future ideas for Context Mind

Captured from our discussion on 2026-10-30.

This is an idea backlog, not an implementation plan or a change to the MVP.
[PROJECT_AGENT_INSTRUCTIONS.md](../PROJECT_AGENT_INSTRUCTIONS.md) remains the
source of truth for scope and development order. Finish the repository assistant
MVP first; choose extensions explicitly afterward. Recording an idea here does
not authorize implementing it, including integrations excluded from the MVP.

## Possible direction

Start with a local-first assistant that helps you understand and explain your
own projects. It could later become a private personal knowledge assistant for
information you repeatedly search for, forget, or need to piece together.

The shared foundation is:

```text
Read information -> split into chunks -> index -> retrieve relevant passages
-> generate an answer with references to the original sources
```

The model receives retrieved information when answering; indexing documents does
not permanently train the model on them. Useful answers depend on source quality,
retrieval accuracy, and checking the evidence.

## Repositories, learning, and career support

| Idea | Example question or result |
| --- | --- |
| Explain a codebase | "How does authentication work, and which files implement it?" |
| Prepare for changes | "Which files should I understand before changing this feature?" |
| Summarize a project | Purpose, architecture, technologies, features, and technical decisions, with code references |
| Search multiple repositories | "Where have I implemented validation and error handling?" |
| Compare approaches | "How did I handle configuration in these two projects?" |
| Summarize demonstrated skills | Examples of Python, backend development, testing, deployment, and other work supported by source evidence |
| Prepare portfolio descriptions | Turn verified project details into clear descriptions of what was built |
| Draft CV bullets | "Implemented configurable local LLM integration with request validation and tested failure handling" |
| Prepare for interviews | Explain design choices, tradeoffs, lessons learned, and concrete examples |
| Match a job description | Connect requirements to project evidence and identify requirements not demonstrated by the indexed work |
| Draft job applications | Use a reviewed CV and project evidence to tailor an application |

Code can demonstrate implementation choices, but it cannot establish a complete
assessment of personal ability. Distinguish your contributions from collaborators,
dependencies, generated code, and AI assistance. Review claims before putting
them in a CV or application, and do not invent responsibilities or outcomes.

## Other information sources

| Source | Possible use | Additional work |
| --- | --- | --- |
| Markdown and personal notes | Find decisions, connect notes, and resume unfinished projects | Folder ingestion outside Git and document metadata |
| Project and home-server documentation | Explain setup, troubleshooting, and maintenance procedures | Index selected documentation and preserve references |
| PDFs, manuals, and reports | Answer questions about documents and appliance instructions | PDF text extraction, page references, and OCR for scanned pages |
| Course materials | Explain topics using supplied material and generate practice questions | Format-specific readers and references to course sources |
| CV and project descriptions | Support portfolio and application drafting | Explicitly selected personal documents and reviewed facts |
| Receipts, contracts, and warranties | Find purchase details, terms, and relevant dates | Document extraction, structured dates, and source verification |

The retrieval and answer-generation pipeline can be reused, but each source type
needs a suitable reader, exclusion rules, and reference metadata. For example,
PDF answers should cite pages rather than code line numbers.

## Everyday questions this could help with

- "Why did I choose this internet plan, and when does the contract end?"
- "What maintenance does my washing machine need according to its manual?"
- "Where did I leave off with the home server, and what did I plan to do next?"
- "What have I built this month, and what did I learn?"
- "Explain this topic using my course materials, then quiz me."
- "Summarize the questions I wrote down for my next appointment or meeting."
- "Find the monitor receipt and the warranty terms that apply to it."

These answers require relevant documents or notes to have been supplied and kept
current. The assistant should show supporting sources and say when information
is missing or conflicting.

## Answering versus taking action

Searching, explaining, summarizing, drafting, and producing checklists fit the
planned RAG approach.

Reminders, calendar updates, sending messages, and controlling devices would need
separate tools and integrations. They also need scheduling where relevant,
appropriate permissions, and confirmation for consequential actions. Finding a
contract end date in a document does not itself create a reminder.

Calendar, email, and Home Assistant integrations are explicitly outside the
current MVP. Consider them only if requested as a later scope change.

## Repository input options

- Current approach: scan a local Git working tree using its absolute path.
- Possible extension: accept an extracted source folder without Git metadata.
- Possible extension: upload a GitHub ZIP export and scan extracted source files.

ZIP support would need safe archive extraction, upload and extraction limits,
path-traversal protection, cleanup, and file exclusions. Folder ingestion without
Git would also need its own file listing and ignore-rule handling. The current
Git requirement belongs to the scanner; the AI itself only needs source content.

## Suggested order after the MVP

1. Validate repository answers against a small set of known questions and sources.
2. Add project summaries with verifiable code references.
3. Add personal Markdown notes and project documentation outside Git.
4. Add multiple repositories and evidence-based portfolio/interview support.
5. Select another document type only when it solves a recurring practical need.
6. Consider action-taking integrations separately if there is a specific use case.

Prefer one useful extension at a time. Continue the implementation phases in
[PROJECT_AGENT_INSTRUCTIONS.md](../PROJECT_AGENT_INSTRUCTIONS.md). This backlog
does not replace the remaining MVP phases.
