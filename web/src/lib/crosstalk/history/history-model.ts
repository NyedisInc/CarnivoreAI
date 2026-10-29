
export type HistoryScope = 'all' | 'project' | 'session';

export const HISTORY_SCOPES: readonly HistoryScope[] = ['all', 'project', 'session'];

export interface HistoryTarget {
  sessionId?: string | null;
  sessionUuid?: string | null;
  rowId?: number | null;
  projectId?: number | null;
}

export interface HistoryFilter {
  session?: string;
  session_row?: number;
  project?: number;
}

export type HistoryRefusal = 'no_session' | 'no_project';

export type FilterAnswer = { filter: HistoryFilter } | { refusal: HistoryRefusal };

export interface ThreadParticipant {
  key: string;
  id: string;
  session_uuid: string | null;
  name: string;
  provider: string | null;
  model: string | null;
  project_id: number | null;
  project_name: string | null;
}

export interface CrosstalkThread {
  thread: string;
  participants: ThreadParticipant[];
  message_count: number;
  last_at: number;
  first_at: number;
  last_preview: string;
  last_sender_key: string;
  last_status: string;
}

export interface ThreadsPage {
  threads: CrosstalkThread[];
  next_before: number | null;
}

export function filterFor(scope: HistoryScope, target: HistoryTarget | null | undefined): FilterAnswer {
  if (scope === 'all') return { filter: {} };
  if (scope === 'project') {
    const project = target?.projectId;
    if (typeof project === 'number' && project > 0) return { filter: { project } };
    return { refusal: hasSession(target) ? 'no_project' : 'no_session' };
  }
  if (!hasSession(target)) return { refusal: 'no_session' };
  const filter: HistoryFilter = {};
  const session = target?.sessionUuid || target?.sessionId;
  if (session) filter.session = session;
  if (typeof target?.rowId === 'number' && target.rowId > 0) filter.session_row = target.rowId;
  return { filter };
}

function hasSession(target: HistoryTarget | null | undefined): boolean {
  return Boolean(target?.sessionUuid || target?.sessionId || (typeof target?.rowId === 'number' && target.rowId > 0));
}

export function threadsPath(filter: HistoryFilter, before: number | null, limit: number): string {
  const query = new URLSearchParams();
  if (filter.session) query.set('session', filter.session);
  if (filter.session_row != null) query.set('session_row', String(filter.session_row));
  if (filter.project != null) query.set('project', String(filter.project));
  if (before != null) query.set('before', String(before));
  query.set('limit', String(limit));
  return `/crosstalk/threads?${query.toString()}`;
}

export function threadMessagesPath(thread: string, before: number | null): string {
  const tail = before == null ? '' : `?before=${encodeURIComponent(String(before))}`;
  return `/crosstalk/threads/${encodeURIComponent(thread)}/messages${tail}`;
}

export function perspectiveOf(thread: CrosstalkThread, target: HistoryTarget | null | undefined): ThreadParticipant {
  const ids = [target?.sessionUuid, target?.sessionId].filter((v): v is string => Boolean(v));
  const own = thread.participants.find((p) => ids.some((id) => id === p.key || id === p.id || id === p.session_uuid));
  return own ?? thread.participants[0]!;
}

export function otherSide(thread: CrosstalkThread, self: ThreadParticipant): ThreadParticipant {
  return thread.participants.find((p) => p.key !== self.key) ?? self;
}

export const THREAD_HEAD_MIN_WIDTH = 300;

export const SCOPE_MEMORY_KEY = 'carnivore.crosstalk.history.scope';

export function readScope(raw: string | null | undefined): HistoryScope | null {
  return HISTORY_SCOPES.includes(raw as HistoryScope) ? (raw as HistoryScope) : null;
}
