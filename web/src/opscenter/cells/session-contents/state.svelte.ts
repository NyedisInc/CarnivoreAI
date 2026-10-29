import { ApiError } from '../../api/auth.svelte';
import { getContents } from './api';
import { totalItems } from './model';
import type { SessionContents } from './types';

export type ContentsStatus = 'idle' | 'loading' | 'ok' | 'error';

export class ContentsStore {
  status = $state<ContentsStatus>('idle');
  data = $state.raw<SessionContents | null>(null);
  errorCode = $state<string | null>(null);
  private rowId: number | null = null;
  private generation = 0;

  follow(rowId: number | null): void {
    if (rowId === this.rowId && this.status !== 'idle') return;
    this.rowId = rowId;
    void this.read();
  }

  refresh(): void {
    void this.read();
  }

  private async read(): Promise<void> {
    const ticket = ++this.generation;
    const rowId = this.rowId;
    if (rowId === null) {
      this.status = 'idle';
      this.data = null;
      this.errorCode = null;
      return;
    }
    this.status = 'loading';
    try {
      const answer = await getContents(rowId);
      if (ticket !== this.generation) return;
      this.data = answer;
      this.errorCode = null;
      this.status = 'ok';
    } catch (error) {
      if (ticket !== this.generation) return;
      this.data = null;
      this.errorCode = error instanceof ApiError ? error.code : null;
      this.status = 'error';
    }
  }
}

const held = new Map<number, { store: ContentsStore; users: number }>();

const latest = $state<{ store: ContentsStore | null }>({ store: null });

export interface ContentsLease {
  store: ContentsStore;
  release(): void;
}

export function acquireContents(rowId: number | null): ContentsLease {
  if (rowId === null) {
    const idle = new ContentsStore();
    return { store: idle, release: () => undefined };
  }
  const entry = held.get(rowId) ?? { store: new ContentsStore(), users: 0 };
  if (entry.users === 0) {
    held.set(rowId, entry);
    entry.store.follow(rowId);
  }
  entry.users += 1;
  latest.store = entry.store;
  return {
    store: entry.store,
    release(): void {
      entry.users -= 1;
      if (entry.users > 0) return;
      held.delete(rowId);
      if (latest.store === entry.store) latest.store = null;
    },
  };
}

export function contentsCount(): number | null {
  return totalItems(latest.store?.data ?? null);
}
