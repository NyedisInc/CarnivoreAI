import type { AnswerSet, DraftResult } from './board-client';

export const DEBOUNCE_MS = 1500;
export const LIMITED_BACKOFF_MS = 30_000;

export type SaveLight = 'idle' | 'waiting' | 'saved' | 'failed';

export interface Autosave {
  change(answers: AnswerSet): void;
  flush(): Promise<void>;
  stop(): void;
}

export function createAutosave(save: (answers: AnswerSet) => Promise<DraftResult>, report: (light: SaveLight, refused?: string) => void,
  timers: { set: (fn: () => void, ms: number) => unknown; clear: (handle: unknown) => void; now?: () => number } = {
    set: (fn, ms) => setTimeout(fn, ms), clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  }): Autosave {
  const now = timers.now ?? Date.now;
  let backoffUntil = 0;
  let pending: AnswerSet | null = null;
  let timer: unknown = null;
  let flying: Promise<void> | null = null;
  let stopped = false;
  let held: AnswerSet | null = null;

  async function write(): Promise<void> {
    if (flying) { await flying; }
    if (stopped || pending === null) return;
    const answers = pending;
    pending = null;
    report('waiting');
    let refused = false;
    flying = save(answers).then((result) => {
      flying = null;
      if (result.kind === 'saved') { report(pending === null ? 'saved' : 'waiting'); return; }
      refused = true;
      report('failed', result.state);
      held = answers;
      if (result.state === 'limited') backoffUntil = now() + LIMITED_BACKOFF_MS;
    });
    await flying;
    if (!refused && pending !== null && !stopped && timer === null) await write();
  }

  return {
    change(answers) {
      if (stopped) return;
      pending = answers;
      held = null;
      report('waiting');
      if (timer !== null) timers.clear(timer);
      timer = timers.set(() => { timer = null; void write(); }, Math.max(DEBOUNCE_MS, backoffUntil - now()));
    },
    async flush() {
      if (timer !== null) { timers.clear(timer); timer = null; }
      if (pending === null && held !== null) pending = held;
      held = null;
      await write();
    },
    stop() {
      stopped = true;
      if (timer !== null) timers.clear(timer);
      timer = null;
    },
  };
}
