/*  hidden  */
import { authFetch } from '../api/auth.svelte';
import { subscribe } from '../api/events.svelte';
import { annotations } from '../cells/analytics/api';
import type { Annotation } from '../cells/analytics/types';
import { t } from '../../lib/i18n/index.svelte';
import type { LivePayload, LogEvent } from './noc';
import type { EventFrame } from '../api/types';

export const FEED_MIN_MS = 15_000;
const TICKER_WINDOW_MS = 24 * 3600_000;

export interface Feed<T> { readonly data: T | null; readonly failure: string; readonly fetchedAt: number | null }

function makeFeed<T>(read: () => Promise<T>, frames: Record<string, (frame: EventFrame) => boolean>): { feed: Feed<T>; watch: () => () => void } {
  const held = $state<{ data: T | null; failure: string; fetchedAt: number | null }>({ data: null, failure: '', fetchedAt: null });
  let watchers = 0;
  let last = 0;
  let inFlight = false;
  /*  hidden  */
  let missed = false;
  let floorTimer: ReturnType<typeof setTimeout> | null = null;
  let stops: (() => void)[] = [];

  async function refresh(force = false): Promise<void> {
    if (inFlight || document.visibilityState === 'hidden') { missed = true; return; }
    const wait = FEED_MIN_MS - (Date.now() - last);
    if (!force && wait > 0) {
      missed = true;
      if (floorTimer === null) floorTimer = setTimeout(() => { floorTimer = null; if (missed) void refresh(); }, wait);
      return;
    }
    missed = false;
    inFlight = true;
    last = Date.now();
    try {
      held.data = await read();
      held.failure = '';
      held.fetchedAt = Date.now();
    } catch (cause: unknown) {
      held.failure = cause instanceof Error ? cause.message : t('analytics.query_failed');
    } finally { inFlight = false; }
  }

  function start(): void {
    void refresh(true);
    const onVisible = (): void => { if (document.visibilityState === 'visible' && missed) void refresh(); };
    document.addEventListener('visibilitychange', onVisible);
    const offFrames = Object.entries(frames).map(([kind, concerns]) =>
      subscribe(kind, (frame) => { if (concerns(frame)) void refresh(); }));
    const offHello = subscribe('events.hello', () => void refresh(true));
    stops = [() => { if (floorTimer !== null) clearTimeout(floorTimer); floorTimer = null; },
      () => document.removeEventListener('visibilitychange', onVisible), ...offFrames, offHello];
  }

  return {
    feed: { get data() { return held.data; }, get failure() { return held.failure; }, get fetchedAt() { return held.fetchedAt; } },
    watch(): () => void {
      if (watchers++ === 0) start();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        if (--watchers === 0) { stops.forEach((stop) => stop()); stops = []; }
      };
    },
  };
}

function changedOf(frame: EventFrame): { live?: boolean; events?: boolean } | undefined {
  return (frame as { changed?: { live?: boolean; events?: boolean } }).changed;
}

const liveFeed = makeFeed<LivePayload>(() => authFetch<LivePayload>('/stats/live'),
  { 'stats.changed': (frame) => changedOf(frame)?.live ?? true });
export const live: Feed<LivePayload> = liveFeed.feed;
export const watchLive: () => () => void = liveFeed.watch;

export interface TickerSource { log: LogEvent[]; marks: Annotation[] }
const tickerFeed = makeFeed<TickerSource>(async () => {
  const to = new Date(Date.now() + 60_000);
  const from = new Date(Date.now() - TICKER_WINDOW_MS);
  const params = new URLSearchParams({ from: from.toISOString(), to: to.toISOString(), limit: '100' });
  const [log, marks] = await Promise.all([
    authFetch<{ items: LogEvent[] }>(`/stats/event-log?${params.toString()}`),
    annotations(from.toISOString(), to.toISOString()),
  ]);
  return { log: log.items, marks };
}, { 'stats.changed': (frame) => changedOf(frame)?.events ?? true, 'stats.tripwire': () => true });
export const ticker: Feed<TickerSource> = tickerFeed.feed;
export const watchTicker: () => () => void = tickerFeed.watch;
