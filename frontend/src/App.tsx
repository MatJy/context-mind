import { useState, type FormEvent } from 'react';
import { askQuestion, indexRepository, type Answer, type Repository } from './api';

export default function App() {
  const [path, setPath] = useState('');
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<{ question: string; answer: Answer } | null>(null);
  const [busy, setBusy] = useState<'index' | 'ask' | null>(null);
  const [error, setError] = useState('');
  const selected = repositories.find((repository) => repository.id === selectedId);

  async function index(event: FormEvent) {
    event.preventDefault();
    if (busy || !path.trim()) return;
    setBusy('index');
    setError('');
    setResult(null);
    try {
      const repository = await indexRepository(path.trim());
      setRepositories((previous) => [...previous.filter((item) => item.id !== repository.id), repository]);
      setSelectedId(repository.id);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Indexing failed. Please try again.');
    } finally {
      setBusy(null);
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (busy || selectedId === null || !question.trim()) return;
    const submittedQuestion = question.trim();
    setBusy('ask');
    setError('');
    setResult(null);
    try {
      const answer = await askQuestion(selectedId, submittedQuestion);
      setResult({ question: submittedQuestion, answer });
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not answer the question. Please try again.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">LOCAL CODEBASE ASSISTANT</p>
        <h1>Context Mind</h1>
        <p>Ask your codebase. Follow the sources.</p>
      </header>

      <section aria-labelledby="repository-heading">
        <h2 id="repository-heading">1. Index a repository</h2>
        <p id="path-help">Enter an absolute Git repository path on the machine running the backend.</p>
        <form onSubmit={index}>
          <label htmlFor="repository-path">Repository path</label>
          <div className="path-row">
            <input id="repository-path" value={path} onChange={(event) => setPath(event.target.value)}
              placeholder="C:/projects/my-repository" maxLength={4096} required
              aria-describedby="path-help" disabled={busy !== null} />
            <button disabled={busy !== null || !path.trim()} type="submit">
              {busy === 'index' ? 'Indexing…' : 'Index repository'}
            </button>
          </div>
        </form>
        {repositories.length > 0 && (
          <div className="repository-summary">
            <label htmlFor="repository-select">Selected repository</label>
            <select id="repository-select" value={selectedId ?? ''} disabled={busy !== null}
              onChange={(event) => {
                setSelectedId(Number(event.target.value));
                setResult(null);
                setError('');
              }}>
              {repositories.map((repository) => (
                <option key={repository.id} value={repository.id}>{repository.name} — {repository.path}</option>
              ))}
            </select>
            {selected && (
              <div role="status">
                <p>{selected.chunk_count} chunks · {selected.embedded_chunk_count} embedded · {selected.reused_chunk_count} reused</p>
                <p className="muted">Indexed {new Date(selected.indexed_at).toLocaleString()}. Re-index this path after code changes.</p>
                {selected.skipped_files.length > 0 && (
                  <details>
                    <summary>{selected.skipped_files.length} files skipped</summary>
                    <ul>{selected.skipped_files.map((file, index) => (
                      <li key={index}><code>{file.file_path}</code> — {file.reason.replaceAll('_', ' ')}</li>
                    ))}</ul>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
        <p className="muted">Selection lasts for this page session. Index the same path again after a refresh to reuse unchanged embeddings.</p>
      </section>

      <section aria-labelledby="question-heading">
        <h2 id="question-heading">2. Ask about the code</h2>
        <form onSubmit={ask}>
          <label htmlFor="question">Your question</label>
          <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
            placeholder="How are unsafe files excluded from indexing?" rows={4} maxLength={8000}
            required disabled={busy !== null || !selected} />
          <button type="submit" disabled={busy !== null || !selected || !question.trim()}>
            {busy === 'ask' ? 'Finding an answer…' : 'Ask question'}
          </button>
          {!selected && <p className="muted">Index a repository to start asking questions.</p>}
        </form>
      </section>

      {busy && <p role="status">{busy === 'index'
        ? 'Scanning files and generating local embeddings. Large repositories may take a while.'
        : 'Retrieving source context and waiting for the local model…'}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {result && (
        <section aria-labelledby="answer-heading" aria-live="polite">
          <h2 id="answer-heading">Answer</h2>
          <p className="muted">{result.question}</p>
          <div className="answer">{result.answer.answer}</div>
          <h3>Sources</h3>
          <p className="muted">Numbered references match citations in the answer. Lines refer to the indexed snapshot.</p>
          {result.answer.sources.length === 0 ? <p>No source references were returned.</p> : (
            <ul className="sources">{result.answer.sources.map((source) => (
              <li key={source.source_id}>
                <span className="citation">[{source.source_id}]</span>{' '}
                <code>{source.file_path}</code>{' '}
                <span className="muted">lines {source.start_line}–{source.end_line}</span>
              </li>
            ))}</ul>
          )}
        </section>
      )}
    </main>
  );
}
