/*  hidden  */
import { subscribe } from '../../api/events.svelte';
import type { EventFrame } from '../../api/types';
import type { StatsChanged } from './state.svelte';

export const COALESCE_MS = 1000;

type Pending = StatsChanged | 'full' | null;

function orNamed(a: boolean | undefined, b: boolean | undefined): boolean | undefined {
  return a === undefined || b === undefined ? undefined : a || b;
}

export function merge(held: Pending, next: StatsChanged | undefined): Pending {
  if (held === 'full' || next === undefined) return 'full';
  if (held === null) return { ...next, metrics: [...next.metrics] };
  return {
    metrics: [...new Set([...held.metrics, ...next.metrics])],
    live: held.live || next.live,
    events: held.events || next.events,
    dimensions: held.dimensions || next.dimensions,
    coverage: orNamed(held.coverage, next.coverage),
    tripwires: orNamed(held.tripwires, next.tripwires),
    clock_only: Boolean(held.clock_only && next.clock_only),
  };
}

export interface FrameDeps {
  refreshAll: () => void;
  apply: (changed: StatsChanged) => void;
  hidden?: () => boolean;
}

export function followStatsFrames(deps: FrameDeps): () => void {
  const hidden = deps.hidden ?? ((): boolean => typeof document !== 'undefined' && document.hidden);
  let pending: Pending = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  /*  hidden  */
  function flush(): void {
    timer = null;
    if (pending === null || hidden()) return;
    const run = pending;
    pending = null;
    if (run === 'full') deps.refreshAll();
    else deps.apply(run);
  }

  function queue(next: StatsChanged | undefined): void {
    pending = merge(pending, next);
    if (timer === null && !hidden()) timer = setTimeout(flush, COALESCE_MS);
  }

  const onVisible = (): void => {
    if (!hidden() && pending !== null && timer === null) flush();
  };
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible);
  const offStats = subscribe('stats.changed', (frame: EventFrame) => queue((frame as { changed?: StatsChanged }).changed));
  const offHello = subscribe('events.hello', () => queue(undefined));
  return () => {
    offStats();
    offHello();
    if (timer !== null) clearTimeout(timer);
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible);
  };
}
