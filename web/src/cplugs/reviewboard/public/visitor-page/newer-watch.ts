/* a newer revision */
import type { NextResult } from './board-client';

export const BACKOFF_S = 30;
export const MIN_GAP_MS = 2000;

export interface WatchDocument {
  readonly hidden: boolean;
  addEventListener(type: 'visibilitychange', fn: () => void): void;
  removeEventListener(type: 'visibilitychange', fn: () => void): void;
}

export function watchNewer(ask: () => Promise<NextResult>, newer: (revision: string) => void, doc: WatchDocument,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((done) => setTimeout(done, ms)), now: () => number = Date.now): () => void {
  let stopped = false;
  let running = false;

  async function loop(): Promise<void> {
    if (running) return;
    running = true;
    try {
      while (!stopped && !doc.hidden) {
        const asked = now();
        const answer = await ask();
        if (stopped) return;
        if (answer.kind === 'newer') { stopped = true; newer(answer.revision); return; }
        if (answer.kind === 'state' && (answer.state === 'ended' || answer.state === 'invalid')) { stopped = true; return; }
        if (answer.kind === 'fixed') {
          if (!answer.retry) { stopped = true; return; }
          await sleep(answer.retry * 1000);
          continue;
        }
        if (answer.kind === 'state') await sleep(BACKOFF_S * 1000);
        else if (answer.retry) await sleep(answer.retry * 1000);
        else if (now() - asked < MIN_GAP_MS) await sleep(MIN_GAP_MS - (now() - asked));
      }
    } finally {
      running = false;
    }
  }

  const onVisible = (): void => { if (!doc.hidden) void loop(); };
  doc.addEventListener('visibilitychange', onVisible);
  void loop();
  return () => {
    stopped = true;
    doc.removeEventListener('visibilitychange', onVisible);
  };
}
