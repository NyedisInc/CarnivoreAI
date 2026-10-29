import { authFetch } from '../../../opscenter/api/auth.svelte';
import { resourcePush } from '../../resource-push/boot';
import {
  threadMessagesPath, threadsPath, type CrosstalkThread, type HistoryFilter, type ThreadsPage,
} from '../history/history-model';

export interface ThreadMessage {
  id: string;
  source: string;
  thread: string;
  sender_key?: string | null;
  receiver_key?: string | null;
  sender_id: string;
  sender_uuid: string | null;
  sender_name: string;
  receiver_id: string;
  receiver_uuid: string | null;
  receiver_name?: string | null;
  text: string;
  status: string;
  reason?: string | null;
  in_reply_to?: string | null;
  expect_reply?: number | boolean | null;
  created_at: number;
}

const PAGE = 50;
const PAGE_MAX = 200;
const FALLBACK_MS = 30000;

export type ReadState = 'loading' | 'ready' | 'failed';

function why(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class Conversations {
  threads = $state<CrosstalkThread[]>([]);
  nextBefore = $state<number | null>(null);
  state = $state<ReadState>('loading');
  reason = $state('');
  openId = $state<string | null>(null);
  messages = $state<ThreadMessage[]>([]);
  olderAt = $state<number | null>(null);
  threadState = $state<ReadState>('loading');
  threadReason = $state('');

  #filter: HistoryFilter | null = null;
  #shown = true;
  #stale = false;
  #request = 0;
  #threadRequest = 0;

  setFilter(filter: HistoryFilter | null): void {
    this.#filter = filter;
    this.threads = [];
    this.nextBefore = null;
    this.state = 'loading';
    this.close();
    this.#refresh();
  }

  setShown(shown: boolean): void {
    this.#shown = shown;
    if (shown && this.#stale) this.#refresh();
  }

  follow(): () => void {
    return resourcePush().pushOrPoll(() => this.#refresh(), FALLBACK_MS, ['crosstalk']);
  }

  #refresh(): void {
    if (!this.#shown) {
      this.#stale = true;
      return;
    }
    this.#stale = false;
    void this.load();
  }

  async load(): Promise<void> {
    const filter = this.#filter;
    if (!filter) return;
    const mine = ++this.#request;
    const limit = Math.min(Math.max(this.threads.length, PAGE), PAGE_MAX);
    try {
      const page = await authFetch<ThreadsPage>(threadsPath(filter, null, limit));
      if (mine !== this.#request) return;
      this.threads = Array.isArray(page.threads) ? page.threads : [];
      this.nextBefore = page.next_before ?? null;
      this.state = 'ready';
      if (this.openId) void this.#loadThread(this.openId, false);
    } catch (error) {
      if (mine !== this.#request) return;
      this.reason = why(error);
      this.state = 'failed';
    }
  }

  async more(): Promise<void> {
    const filter = this.#filter;
    if (!filter || this.nextBefore == null) return;
    const mine = ++this.#request;
    try {
      const page = await authFetch<ThreadsPage>(threadsPath(filter, this.nextBefore, PAGE));
      if (mine !== this.#request) return;
      const seen = new Set(this.threads.map((row) => row.thread));
      this.threads = [...this.threads, ...(page.threads ?? []).filter((row) => !seen.has(row.thread))];
      this.nextBefore = page.next_before ?? null;
    } catch (error) {
      if (mine !== this.#request) return;
      this.reason = why(error);
      this.state = 'failed';
    }
  }

  open(thread: string): void {
    if (this.openId === thread) return;
    this.openId = thread;
    this.messages = [];
    this.olderAt = null;
    this.threadState = 'loading';
    void this.#loadThread(thread, false);
  }

  close(): void {
    this.openId = null;
    this.messages = [];
    this.olderAt = null;
    this.#threadRequest += 1;
  }

  older(): Promise<void> {
    return this.openId ? this.#loadThread(this.openId, true) : Promise.resolve();
  }

  async #loadThread(thread: string, older: boolean): Promise<void> {
    const mine = ++this.#threadRequest;
    try {
      const page = await authFetch<{ messages: ThreadMessage[]; next_before: number | null }>(
        threadMessagesPath(thread, older ? this.olderAt : null));
      if (mine !== this.#threadRequest || this.openId !== thread) return;
      const rows = Array.isArray(page.messages) ? page.messages : [];
      if (older) {
        const seen = new Set(this.messages.map((m) => m.id));
        this.messages = [...rows.filter((m) => !seen.has(m.id)), ...this.messages];
        this.olderAt = page.next_before ?? null;
      } else {
        const fresh = new Set(rows.map((m) => m.id));
        const firstAt = rows[0]?.created_at ?? Number.POSITIVE_INFINITY;
        const kept = this.messages.filter((m) => !fresh.has(m.id) && m.created_at < firstAt);
        this.messages = [...kept, ...rows];
        if (kept.length === 0) this.olderAt = page.next_before ?? null;
      }
      this.threadState = 'ready';
    } catch (error) {
      if (mine !== this.#threadRequest) return;
      this.threadReason = why(error);
      this.threadState = 'failed';
    }
  }
}
