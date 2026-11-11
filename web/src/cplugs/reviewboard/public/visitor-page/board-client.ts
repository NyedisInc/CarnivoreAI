import { LINK_HEADER } from './fragment';

export const VISITOR_HEADER = 'Carnivore-Visitor';
const REVISION_HEADER = 'Carnivore-Revision';

function headersFor(secret: string, visitor: string | null): Record<string, string> {
  return visitor ? { [LINK_HEADER]: secret, [VISITOR_HEADER]: visitor } : { [LINK_HEADER]: secret };
}

export type PageState = 'invalid' | 'ended' | 'limited' | 'misrouted' | 'unavailable';
const STATES: readonly PageState[] = ['invalid', 'ended', 'limited', 'misrouted', 'unavailable'];

export interface PublicView { id: string; label: string; frame: string }
export interface PublicPrompt { id: string; kind: string; label: string; anchor?: string | null; options: Array<{ id: string; label: string }> }
export interface PublicAnchor { id: string; label: string }
export type PagePayload = Record<string, unknown>;
export type AnswerSet = { answers: AnswerBody[] } | { payload: PagePayload };
export interface OwnDraft { body: AnswerSet }
export type LinkAccess = 'answer' | 'read';
export interface PublicBoardData {
  title: string;
  revision: string;
  frame_ttl?: number;
  summary?: string;
  viewport?: number;
  max_width?: number | null;
  views: PublicView[];
  prompts?: PublicPrompt[];
  anchors?: PublicAnchor[];
  layer?: Record<string, unknown> | null;
  expires_at?: number;
  access?: LinkAccess;
  theme?: Record<string, string> | null;
  draft?: OwnDraft | null;
  revisions?: Array<{ revision: string; answered: boolean }>;
}
export type BoardResult = { kind: 'board'; board: PublicBoardData } | { kind: 'state'; state: PageState };

export type Fetcher = (input: string, init: RequestInit) => Promise<Response>;

export async function fetchBoard(secret: string | null, fetcher: Fetcher = (url, init) => fetch(url, init), visitor: string | null = null,
  revision: string | null = null): Promise<BoardResult> {
  if (secret === null) return { kind: 'state', state: 'invalid' };
  let res: Response;
  try {
    res = await fetcher('/api/board', {
      headers: { ...headersFor(secret, visitor), ...(revision ? { [REVISION_HEADER]: revision } : {}) }, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer',
    });
  } catch (error) {
    if (error instanceof TypeError) return { kind: 'state', state: 'unavailable' };
    throw error;
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) return { kind: 'state', state: stateOf(body) };
  return isBoard(body) ? { kind: 'board', board: body } : { kind: 'state', state: 'unavailable' };
}

function stateOf(body: unknown): PageState {
  const named = typeof body === 'object' && body !== null ? (body as { state?: unknown }).state : undefined;
  if (typeof named === 'string' && (STATES as readonly string[]).includes(named)) return named as PageState;
  return 'unavailable';
}

function isBoard(body: unknown): body is PublicBoardData {
  if (typeof body !== 'object' || body === null) return false;
  const b = body as Partial<PublicBoardData>;
  return typeof b.title === 'string' && typeof b.revision === 'string' && Array.isArray(b.views) && b.views.length > 0
    && b.views.every((v) => typeof v?.id === 'string' && typeof v?.frame === 'string');
}

export type PostState = PageState | 'malformed' | 'rejected' | 'has_secret' | 'full' | 'read_only' | 'stale';
const POST_STATES: readonly PostState[] = [...STATES, 'malformed', 'rejected', 'has_secret', 'full', 'read_only', 'stale'];
export type PostRoute = 'comments';
const POST_PATHS: Record<PostRoute, string> = { comments: '/api/comments' };
export interface AnswerBody { prompt: string; options?: string[]; checked?: boolean; text?: string; note?: string }
export type PostBody = { client_post_id: string; name?: string; revision?: string; text: string; anchor?: string };
export type PostResult = { kind: 'received'; duplicate: boolean } | { kind: 'state'; state: PostState };

export async function postToBoard(secret: string | null, route: PostRoute, body: PostBody,
  fetcher: Fetcher = (url, init) => fetch(url, init), visitor: string | null = null): Promise<PostResult> {
  const sent = await postJson(secret, POST_PATHS[route], body, fetcher, visitor);
  if (sent.kind === 'state') return sent;
  return { kind: 'received', duplicate: sent.status === 200 };
}

type Posted = { kind: 'ok'; status: number; body: unknown } | { kind: 'state'; state: PostState };

async function postJson(secret: string | null, path: string, body: unknown, fetcher: Fetcher, visitor: string | null, keepalive = false): Promise<Posted> {
  if (secret === null) return { kind: 'state', state: 'invalid' };
  let res: Response;
  try {
    res = await fetcher(path, {
      method: 'POST', body: JSON.stringify(body), cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer', keepalive,
      headers: { ...headersFor(secret, visitor), 'Content-Type': 'application/json' },
    });
  } catch (error) {
    if (error instanceof TypeError) return { kind: 'state', state: 'unavailable' };
    throw error;
  }
  const answer: unknown = await res.json().catch(() => null);
  if (res.ok) return { kind: 'ok', status: res.status, body: answer };
  const named = typeof answer === 'object' && answer !== null ? (answer as { state?: unknown }).state : undefined;
  if (typeof named === 'string' && (POST_STATES as readonly string[]).includes(named)) return { kind: 'state', state: named as PostState };
  return { kind: 'state', state: 'unavailable' };
}

export type DraftResult = { kind: 'saved'; changed: boolean } | { kind: 'state'; state: PostState };

export async function saveDraftTo(secret: string | null, visitor: string | null, body: { revision: string } & AnswerSet,
  fetcher: Fetcher = (url, init) => fetch(url, init)): Promise<DraftResult> {
  const sent = await postJson(secret, '/api/draft', body, fetcher, visitor, true);
  if (sent.kind === 'state') return sent;
  return { kind: 'saved', changed: (sent.body as { changed?: unknown } | null)?.changed === true };
}

export type NextResult = { kind: 'newer'; revision: string } | { kind: 'same'; retry: number | null } | { kind: 'fixed'; retry?: number | null } | { kind: 'state'; state: PageState };

/* a newer revision */
export async function waitNextFrom(secret: string | null, revision: string, fetcher: Fetcher = (url, init) => fetch(url, init),
  visitor: string | null = null): Promise<NextResult> {
  if (secret === null) return { kind: 'state', state: 'invalid' };
  let res: Response;
  try {
    res = await fetcher('/api/next', {
      headers: { ...headersFor(secret, visitor), [REVISION_HEADER]: revision }, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer',
    });
  } catch (error) {
    if (error instanceof TypeError) return { kind: 'state', state: 'unavailable' };
    throw error;
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) return { kind: 'state', state: stateOf(body) };
  const b = (body ?? {}) as { state?: unknown; revision?: unknown; retry?: unknown };
  if (b.state === 'newer' && typeof b.revision === 'string') return { kind: 'newer', revision: b.revision };
  if (b.state === 'fixed') return { kind: 'fixed', retry: typeof b.retry === 'number' ? b.retry : null };
  return { kind: 'same', retry: typeof b.retry === 'number' ? b.retry : null };
}

export type IdSource = Pick<Crypto, 'getRandomValues'> & { randomUUID?: () => string };

export function newPostId(source: IdSource = crypto): string {
  if (typeof source.randomUUID === 'function') return source.randomUUID();
  return [...source.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, '0')).join('');
}
