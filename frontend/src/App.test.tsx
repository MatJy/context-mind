import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';

const repository = {
  id: 7, name: 'demo', path: 'C:/demo', indexed_at: '2026-11-23T10:00:00Z',
  chunk_count: 3, embedded_chunk_count: 2, reused_chunk_count: 1,
  embedding_model: 'local', skipped_files: [{ file_path: '.env', reason: 'excluded' }],
};
const answer = {
  repository_id: 7, answer: 'Unsafe files are excluded [1].\n<script>alert(1)</script>',
  sources: [{ source_id: 1, file_path: 'src/scan.py', start_line: 12, end_line: 30 }],
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

afterEach(() => vi.unstubAllGlobals());

it('indexes a repository, asks against its ID, and displays safe text and source lines', async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValueOnce(json(repository)).mockResolvedValueOnce(json(answer));
  vi.stubGlobal('fetch', fetchMock);
  const { container } = render(<App />);
  expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled();
  await user.type(screen.getByLabelText('Repository path'), ' C:/demo ');
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  expect(await screen.findByText('3 chunks · 2 embedded · 1 reused')).toBeInTheDocument();
  expect(fetchMock.mock.calls[0][0]).toBe('/api/repositories/index');
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ path: 'C:/demo' });
  await user.type(screen.getByLabelText('Your question'), ' How are secrets excluded? ');
  await user.click(screen.getByRole('button', { name: 'Ask question' }));
  expect(await screen.findByText('src/scan.py')).toBeInTheDocument();
  expect(screen.getByText('lines 12–30')).toBeInTheDocument();
  expect(fetchMock.mock.calls[1][0]).toBe('/api/repositories/7/chat');
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ question: 'How are secrets excluded?' });
  expect(container.querySelector('script')).toBeNull();
  expect(screen.getByText(/<script>alert/)).toBeInTheDocument();
});

it('shows indexing progress, blocks duplicate submissions, and recovers from API errors', async () => {
  const user = userEvent.setup();
  let resolve!: (response: Response) => void;
  const fetchMock = vi.fn().mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }))
    .mockResolvedValueOnce(json(repository));
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  await user.type(screen.getByLabelText('Repository path'), 'C:/demo');
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  expect(screen.getByRole('button', { name: 'Indexing…' })).toBeDisabled();
  expect(screen.getByText(/Scanning files/)).toBeInTheDocument();
  resolve(json({ detail: 'Embedding service is unavailable.' }, 503));
  expect(await screen.findByRole('alert')).toHaveTextContent('Embedding service is unavailable.');
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  expect(await screen.findByLabelText('Selected repository')).toHaveValue('7');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('handles failed questions, retries, empty sources, and clears answers when switching repositories', async () => {
  const user = userEvent.setup();
  let resolve!: (response: Response) => void;
  const fetchMock = vi.fn().mockResolvedValueOnce(json(repository))
    .mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }))
    .mockResolvedValueOnce(json({ ...answer, sources: [] }))
    .mockResolvedValueOnce(json({ ...repository, id: 8, name: 'other', path: 'C:/other' }))
    .mockResolvedValueOnce(json({ ...answer, repository_id: 8 }));
  vi.stubGlobal('fetch', fetchMock);
  render(<App />);
  await user.type(screen.getByLabelText('Repository path'), 'C:/demo');
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  await screen.findByLabelText('Selected repository');
  await user.type(screen.getByLabelText('Your question'), 'Explain scanning');
  await user.click(screen.getByRole('button', { name: 'Ask question' }));
  expect(screen.getByRole('button', { name: 'Finding an answer…' })).toBeDisabled();
  expect(screen.getByLabelText('Selected repository')).toBeDisabled();
  resolve(json({ detail: 'Model timed out.' }, 504));
  expect(await screen.findByRole('alert')).toHaveTextContent('Model timed out.');
  await user.click(screen.getByRole('button', { name: 'Ask question' }));
  expect(await screen.findByText('No source references were returned.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Repository path'), { target: { value: 'C:/other' } });
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  await waitFor(() => expect(screen.getByLabelText('Selected repository')).toHaveValue('8'));
  await user.click(screen.getByRole('button', { name: 'Ask question' }));
  await screen.findByRole('heading', { name: 'Answer' });
  expect(fetchMock.mock.calls[4][0]).toBe('/api/repositories/8/chat');
  await user.selectOptions(screen.getByLabelText('Selected repository'), '7');
  expect(screen.queryByRole('heading', { name: 'Answer' })).not.toBeInTheDocument();
});

it.each([
  [() => Promise.reject(new TypeError('Failed to fetch')), 'Could not reach the API'],
  [() => Promise.resolve(new Response('Bad gateway', { status: 502 })), 'Request failed (502)'],
  [() => Promise.resolve(json({ detail: [{ msg: 'Path is required' }] }, 422)), 'Path is required'],
])('reports network, proxy, and validation failures', async (response, message) => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(response));
  const user = userEvent.setup();
  render(<App />);
  await user.type(screen.getByLabelText('Repository path'), 'C:/demo');
  await user.click(screen.getByRole('button', { name: 'Index repository' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
});
