import { authFetch } from '../../opscenter/api/auth.svelte';

export const WINDOW_SIZE = 20;

export interface ContextMessage {
  line: number;
  kind: string;
  role: string;
  text: string;
  at: string | null;
}

export interface ContextMark {
  id: number | null;
  label: string;
  at: string;
  afterLine: number | null;
}

export interface ContextWindow {
  anchor: number | null;
  messages: ContextMessage[];
  hasBefore: boolean;
  hasAfter: boolean;
  bookmarks: ContextMark[];
}

export interface ContextRequest {
  conversationId: string;
  fileKind: 'conversation' | 'subagent';
  hostKey: string | null;
  line?: number;
  at?: string;
  beforeLine?: number;
  afterLine?: number;
}

type Bag = Record<string, unknown>;
const isBag = (v: unknown): v is Bag => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function readWindow(raw: unknown): ContextWindow {
  const body = isBag(raw) ? raw : {};
  const messages = (Array.isArray(body.messages) ? body.messages : []).flatMap((m): ContextMessage[] => {
    if (!isBag(m) || num(m.line) === null || typeof m.text !== 'string') return [];
    const kind = typeof m.kind === 'string' ? m.kind : 'user';
    return [{ line: m.line as number, kind, role: typeof m.role === 'string' ? m.role : kind, text: m.text, at: typeof m.at === 'string' ? m.at : null }];
  });
  const bookmarks = (Array.isArray(body.bookmarks) ? body.bookmarks : []).flatMap((b): ContextMark[] =>
    isBag(b) && typeof b.at === 'string'
      ? [{ id: num(b.id), label: typeof b.label === 'string' ? b.label : '', at: b.at, afterLine: num(b.after_line) }]
      : [],
  );
  return { anchor: num(body.anchor), messages, hasBefore: body.has_before === true, hasAfter: body.has_after === true, bookmarks };
}

export async function fetchContext(request: ContextRequest, before: number, after: number, signal?: AbortSignal): Promise<ContextWindow> {
  const params = new URLSearchParams({ conversation_id: request.conversationId, file_kind: request.fileKind, before: String(before), after: String(after) });
  if (request.hostKey && request.hostKey !== 'local') params.set('host_key', request.hostKey);
  for (const [key, value] of [['line', request.line], ['at', request.at], ['before_line', request.beforeLine], ['after_line', request.afterLine]] as const) {
    if (value !== undefined) params.set(key, String(value));
  }
  return readWindow(await authFetch<unknown>(`/deepsearch/context?${params.toString()}`, { signal }));
}

export interface BranchedSession {
  sessionId: string;
  tmuxName: string;
}

export async function branchBookmark(bookmarkId: number): Promise<BranchedSession> {
  return readBranched(await authFetch<unknown>(`/bookmarks/${bookmarkId}/branch`, { method: 'POST', body: '{}' }));
}

export function readBranched(made: unknown): BranchedSession {
  const session = isBag(made) && isBag(made.session) ? made.session : {};
  return { sessionId: typeof session.id === 'string' ? session.id : '', tmuxName: typeof session.tmux_session === 'string' ? session.tmux_session : '' };
}
