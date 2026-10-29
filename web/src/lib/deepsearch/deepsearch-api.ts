import { authFetch } from '../../opscenter/api/auth.svelte';

export const PAGE_SIZE = 20;
export const PER_GROUP = 3;

export interface HitBookmark {
  id: number | null;
  label: string;
  at: string;
}

export interface DeepHit {
  line: number | null;
  kind: string;
  snippet: string;
  fileKind: 'conversation' | 'subagent';
  at: string | null;
  bookmark: HitBookmark | null;
  entryUuid: string | null;
  fromBackup: boolean;
}

export interface ExportedInfo {
  bundleId: string;
  label: string | null;
  exportedAt: string | null;
  localRemoved: boolean;
}

export interface DeepGroup {
  conversationId: string;
  matches: number;
  sessionUuid: string | null;
  session: string | null;
  projectId: number | null;
  project: string | null;
  firstPrompt: string | null;
  workingDir: string | null;
  lastActive: string | null;
  family: string | null;
  subagentMatches: number;
  hostKey: string | null;
  hostLabel: string | null;
  alsoOn: string[];
  exported: ExportedInfo | null;
  hits: DeepHit[];
}

export interface PeerDown {
  hostKey: string;
  label: string;
  notReady: boolean;
}

export interface DeepIngest {
  state: 'running' | 'stalled' | string;
  reason: string | null;
  backlogFiles: number;
  indexScope: string | null;
}

export interface DeepAnswer {
  query: string;
  totalConversations: number;
  totalMatches: number;
  offset: number;
  localTotal: number;
  groups: DeepGroup[];
  ingest: DeepIngest;
  peerDown: PeerDown[];
  stale: string[];
}

type Bag = Record<string, unknown>;
const isBag = (v: unknown): v is Bag => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

function readBookmark(raw: unknown): HitBookmark | null {
  const at = isBag(raw) ? str(raw.at) : null;
  return isBag(raw) && at ? { id: num(raw.id), label: typeof raw.label === 'string' ? raw.label : '', at } : null;
}

function readHit(raw: unknown): DeepHit | null {
  if (!isBag(raw) || typeof raw.snippet !== 'string') return null;
  return {
    at: str(raw.at),
    bookmark: readBookmark(raw.bookmark),
    line: num(raw.line),
    kind: str(raw.kind) ?? 'user',
    snippet: raw.snippet,
    fileKind: raw.file_kind === 'subagent' ? 'subagent' : 'conversation',
    entryUuid: str(raw.entry_uuid),
    fromBackup: raw.from_backup === true,
  };
}

function readExported(raw: unknown): ExportedInfo | null {
  const bundleId = isBag(raw) ? str(raw.bundle_id) : null;
  return isBag(raw) && bundleId
    ? { bundleId, label: str(raw.label), exportedAt: str(raw.exported_at), localRemoved: raw.local_removed === true }
    : null;
}

function readGroup(raw: unknown): DeepGroup | null {
  if (!isBag(raw)) return null;
  const conversationId = str(raw.conversation_id);
  if (!conversationId) return null;
  const byFile = isBag(raw.by_file_kind) ? raw.by_file_kind : {};
  return {
    conversationId,
    matches: num(raw.matches) ?? 0,
    sessionUuid: str(raw.session_uuid),
    session: str(raw.session),
    projectId: num(raw.project_id),
    project: str(raw.project),
    firstPrompt: str(raw.first_prompt),
    workingDir: str(raw.working_dir),
    lastActive: str(raw.last_active),
    family: str(raw.family),
    subagentMatches: num(byFile.subagent) ?? 0,
    hostKey: str(raw.host_key),
    hostLabel: str(raw.host_label),
    alsoOn: (Array.isArray(raw.also_on) ? raw.also_on : []).filter((x): x is string => typeof x === 'string' && x !== ''),
    exported: readExported(raw.exported),
    hits: (Array.isArray(raw.hits) ? raw.hits : []).map(readHit).filter((h): h is DeepHit => h !== null),
  };
}

export function readAnswer(raw: unknown): DeepAnswer {
  const body = isBag(raw) ? raw : {};
  const ingest = isBag(body.ingest) ? body.ingest : {};
  const coverage = isBag(ingest.coverage) ? ingest.coverage : {};
  const totalConversations = num(body.total_conversations) ?? 0;
  const peerDown = (Array.isArray(body.peer_unavailable) ? body.peer_unavailable : []).flatMap((row): PeerDown[] => {
    const key = isBag(row) ? str(row.host_key) : null;
    const label = isBag(row) ? (str(row.host_label) ?? key) : null;
    return key && label ? [{ hostKey: key, label, notReady: isBag(row) && row.reason === 'not_ready' }] : [];
  });
  return {
    query: str(body.query) ?? '',
    totalConversations,
    localTotal: num(body.local_total_conversations) ?? totalConversations,
    totalMatches: num(body.total_matches) ?? 0,
    offset: num(body.offset) ?? 0,
    groups: (Array.isArray(body.groups) ? body.groups : []).map(readGroup).filter((g): g is DeepGroup => g !== null),
    ingest: { state: str(ingest.state) ?? 'running', reason: str(ingest.reason), backlogFiles: num(coverage.backlog_files) ?? 0, indexScope: str(ingest.scope) },
    peerDown,
    stale: (Array.isArray(body.stale) ? body.stale : []).filter((x): x is string => typeof x === 'string' && x !== ''),
  };
}

export const DATABASE_SUGGEST_PATH = '/deepsearch/suggest';
export const SUGGEST_LIMIT = 8;

export interface DeepSuggestion {
  term: string;
  docs: number;
}

export function readSuggestions(raw: unknown): DeepSuggestion[] {
  const terms = isBag(raw) && Array.isArray(raw.terms) ? raw.terms : [];
  return terms.flatMap((row) => {
    const term = isBag(row) ? str(row.term) : null;
    return term ? [{ term, docs: (isBag(row) ? num(row.docs) : null) ?? 0 }] : [];
  });
}

export interface SearchScope {
  kinds?: string;
  conversationId?: string;
}

/* the whole conversation */
export const PER_CONVERSATION_ALL = 10;

export interface DeepSearchApi {
  search(query: string, offset: number, signal: AbortSignal, scope?: SearchScope): Promise<DeepAnswer>;
  readonly filters?: boolean;
  peers?(query: string, signal: AbortSignal, scope?: SearchScope): Promise<DeepAnswer>;
  suggest?(prefix: string, signal: AbortSignal): Promise<DeepSuggestion[]>;
}

export const DATABASE_SEARCH_PATH = '/deepsearch/search';

export function groupedSearchApi(path: string, extra: Record<string, string> = {}, filters = false): DeepSearchApi {
  return {
    filters,
    async search(query, offset, signal, scope) {
      const params = new URLSearchParams({ q: query, limit: String(PAGE_SIZE), offset: String(offset), per_group: String(PER_GROUP), ...extra });
      if (filters && scope?.kinds) params.set('kinds', scope.kinds);
      if (filters && scope?.conversationId) {
        params.set('conversation_id', scope.conversationId);
        params.set('per_group', String(PER_CONVERSATION_ALL));
      }
      return readAnswer(await authFetch<unknown>(`${path}?${params.toString()}`, { signal }));
    },
  };
}

export const browserDeepSearchApi: DeepSearchApi = {
  ...groupedSearchApi(DATABASE_SEARCH_PATH, { scope: 'local' }, true),
  async peers(query, signal, scope) {
    return groupedSearchApi(DATABASE_SEARCH_PATH, { scope: 'peers' }, true).search(query, 0, signal, scope);
  },
  async suggest(prefix, signal) {
    const params = new URLSearchParams({ q: prefix, limit: String(SUGGEST_LIMIT) });
    return readSuggestions(await authFetch<unknown>(`${DATABASE_SUGGEST_PATH}?${params.toString()}`, { signal }));
  },
};
