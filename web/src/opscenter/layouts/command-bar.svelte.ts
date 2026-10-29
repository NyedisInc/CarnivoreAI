import { t } from '../../lib/i18n/index.svelte';
import { TYPE_DEBOUNCE_MS } from '../../lib/terminal-search/search-controller.svelte';
import type { BroadcastAnswer } from './api';
import type { Recipients } from './broadcast.svelte';

export type BarMode = 'search' | 'command';

export type KeyOutcome = 'handled' | 'blur' | 'ignored';

export interface BarSearch {
  run(query: string): void;
  release(): void;
  step(dir: 'next' | 'prev'): void;
}

export interface BarDeps {
  search: BarSearch;
  send(text: string): Promise<BroadcastAnswer>;
  recipients(): Recipients;
  confirmBusy(names: string[]): Promise<boolean>;
  nameOf(rowId: number): string;
  reason(error: unknown): string;
}

export class CommandBar {
  mode = $state<BarMode>('search');
  text = $state('');
  sending = $state(false);
  line = $state('');
  #deps: BarDeps;
  #timer: ReturnType<typeof setTimeout> | null = null;

  constructor(deps: BarDeps) {
    this.#deps = deps;
  }

  setMode(mode: BarMode): void {
    if (mode === this.mode) return;
    this.#cancelTimer();
    if (this.mode === 'search') this.#deps.search.release();
    this.mode = mode;
    this.text = '';
    this.line = '';
  }

  input(value: string): void {
    this.text = value;
    this.line = '';
    if (this.mode !== 'search') return;
    this.#cancelTimer();
    this.#timer = setTimeout(() => {
      this.#timer = null;
      this.#deps.search.run(this.text);
    }, TYPE_DEBOUNCE_MS);
  }

  key(key: string, shift = false): KeyOutcome {
    if (key === 'Escape') {
      if (!this.text) return 'blur';
      this.clear();
      return 'handled';
    }
    if (key !== 'Enter') return 'ignored';
    if (this.mode === 'search') {
      if (this.#timer !== null) {
        this.#cancelTimer();
        this.#deps.search.run(this.text);
      }
      this.#deps.search.step(shift ? 'prev' : 'next');
      return 'handled';
    }
    void this.send();
    return 'handled';
  }

  clear(): void {
    this.#cancelTimer();
    this.text = '';
    this.line = '';
    if (this.mode === 'search') this.#deps.search.release();
  }

  async send(): Promise<void> {
    const text = this.text;
    if (this.mode !== 'command' || this.sending || !text.trim()) return;
    const who = this.#deps.recipients();
    if (who.receiving === 0) {
      this.line = t('layout.bar.nobody');
      return;
    }
    if (who.busy.length > 0 && !(await this.#deps.confirmBusy(who.busy))) return;
    this.sending = true;
    this.line = t('layout.bar.sending');
    try {
      const answer = await this.#deps.send(text);
      if (this.text === text) this.text = '';
      this.line = this.#summary(answer);
    } catch (error) {
      this.line = t('layout.bar.send_failed', { reason: this.#deps.reason(error) });
    } finally {
      this.sending = false;
    }
  }

  #summary(answer: BroadcastAnswer): string {
    const parts: string[] = [];
    if (answer.skipped > 0) parts.push(t('layout.bar.skipped', { count: answer.skipped }));
    const failed = answer.results.filter((one) => one.status === 'failed');
    if (failed.length > 0) {
      const names = failed.map((one) => `${this.#deps.nameOf(one.session_row_id)} (${one.code ?? 'failed'})`);
      parts.push(t('layout.bar.failed', { names: names.join(', ') }));
    }
    return parts.join(', ');
  }

  #cancelTimer(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}
