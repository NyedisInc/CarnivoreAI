import { authFetch } from '../api/auth.svelte';
import { resource, type Resource } from '../api/poll.svelte';
import type { LevelState, LogPage, LogSource } from './types';

export const SERVER_LOG_POLL_MS = 10000;
export const SERVER_LOG_TOPIC = 'server_log';
export const SERVER_LOG_LIMIT = 500;
const LOG_ROUTE = '/server-log';
const LEVEL_ROUTE = '/log-level';

function emptyPage(head: string | null): LogPage {
  return { records: [], head, before: null, gap: false, reset: false };
}

export function pagePath(kind: 'since' | 'before' | null, cursor: string | null): string {
  const base = `${LOG_ROUTE}?v=2&limit=${SERVER_LOG_LIMIT}`;
  return kind && cursor ? `${base}&${kind}=${encodeURIComponent(cursor)}` : base;
}

export class ApiLogSource implements LogSource {
  private readonly fetcher: typeof authFetch;

  constructor(fetcher: typeof authFetch = authFetch) {
    this.fetcher = fetcher;
  }

  backfill(cursor: string): Promise<LogPage> {
    return this.fetcher<LogPage>(pagePath('before', cursor));
  }

  subscribe(onBatch: (page: LogPage) => void, onError?: (error: unknown) => void): () => void {
    let head: string | null = null;
    let stopped = false;
    const read = async (): Promise<LogPage> => {
      if (typeof document !== 'undefined' && document.hidden && head !== null) return emptyPage(head);
      let page: LogPage;
      try {
        page = await this.fetcher<LogPage>(pagePath(head === null ? null : 'since', head));
      } catch (error) {
        if (!stopped) onError?.(error);
        throw error;
      }
      if (stopped) return page;
      const firstRead = head === null;
      head = page.head ?? head;
      if (firstRead || page.records.length || page.reset || page.gap) onBatch(page);
      return page;
    };
    const feed: Resource<LogPage> = resource<LogPage>(read, {
      intervalMs: SERVER_LOG_POLL_MS,
      topics: [SERVER_LOG_TOPIC],
      name: 'server-log',
      demo: () => emptyPage(null),
    });
    const onVisible = (): void => {
      if (!document.hidden) void feed.refresh(true);
    };
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible);
      feed.stop();
    };
  }

  readLevel(): Promise<LevelState> {
    return this.fetcher<LevelState>(LEVEL_ROUTE);
  }

  setLevel(level: string | null): Promise<LevelState> {
    return this.fetcher<LevelState>(LEVEL_ROUTE, { method: 'PUT', body: JSON.stringify({ level }) });
  }
}
