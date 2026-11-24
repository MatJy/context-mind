export interface Repository {
  id: number;
  name: string;
  path: string;
  indexed_at: string;
  chunk_count: number;
  embedded_chunk_count: number;
  reused_chunk_count: number;
  embedding_model: string;
  skipped_files: { file_path: string; reason: string }[];
}

export interface Answer {
  repository_id: number;
  answer: string;
  sources: { source_id: number; file_path: string; start_line: number; end_line: number }[];
}

async function post<T>(path: string, body: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Could not reach the API. Check that FastAPI and the frontend server are running.');
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : null;
    if (typeof detail === 'string') throw new Error(detail);
    if (Array.isArray(detail)) {
      const messages = detail.map((item: { msg?: string }) => item.msg).filter(Boolean);
      if (messages.length) throw new Error(messages.join(' '));
    }
    throw new Error(`Request failed (${response.status}). Check the backend, database, and Ollama services.`);
  }
  if (data === null) throw new Error('The API returned an invalid response. Please try again.');
  return data as T;
}

export const indexRepository = (path: string) => post<Repository>('/repositories/index', { path });
export const askQuestion = (repositoryId: number, question: string) =>
  post<Answer>(`/repositories/${repositoryId}/chat`, { question });
