import { ApiError } from '../../api/auth.svelte';
import { getContents } from './api';
import { totalItems } from './model';
import type { SessionContents } from './types';

export type ContentsStatus = 'idle' | 'loading' | 'ok' | 'error';

class ContentsStore {
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

export const contents = new ContentsStore();

export function contentsCount(): number | null {
  return totalItems(contents.data);
}
