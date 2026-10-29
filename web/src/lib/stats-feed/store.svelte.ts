import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import type { FeedBody, FeedWindow } from './types';

export const STATS_FEED_TOPIC = 'stats_feed';

export const STATS_FEED_FALLBACK_MS = 30000;

export function isFresher(held: FeedBody | null, incoming: FeedBody): boolean {
  return !held || incoming.rev > held.rev || incoming.now >= held.now;
}

interface Entry {
  holders: number;
  res: Resource<FeedBody>;
}

const entries = new Map<FeedWindow, Entry>();
let versionCounter = 0;
let visibleOff: (() => void) | null = null;

export const statsFeedState = $state<{ version: number }>({ version: 0 });

function make(window: FeedWindow): Resource<FeedBody> {
  let made: Resource<FeedBody> | null = null;
  let held: FeedBody | null = null;
  made = resource<FeedBody>(
    async () => {
      if (typeof document !== 'undefined' && document.hidden && held) return held;
      const body = await authFetch<FeedBody>(`/stats/feed?window=${window}`);
      if (isFresher(held, body)) held = body;
      return held as FeedBody;
    },
    { intervalMs: STATS_FEED_FALLBACK_MS, name: `stats-feed:${window}`, topics: [STATS_FEED_TOPIC] },
  );
  return made;
}

export function statsFeed(window: FeedWindow): Resource<FeedBody> | null {
  void statsFeedState.version;
  return entries.get(window)?.res ?? null;
}

export function acquireStatsFeed(window: FeedWindow): () => void {
  let entry = entries.get(window);
  if (!entry) {
    entry = { holders: 0, res: make(window) };
    entries.set(window, entry);
    statsFeedState.version = ++versionCounter;
  }
  entry.holders += 1;
  if (!visibleOff && typeof document !== 'undefined') {
    const onVisible = (): void => {
      if (document.hidden) return;
      for (const e of entries.values()) void e.res.refresh(true);
    };
    document.addEventListener('visibilitychange', onVisible);
    visibleOff = () => document.removeEventListener('visibilitychange', onVisible);
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const e = entries.get(window);
    if (!e) return;
    e.holders -= 1;
    if (e.holders > 0) return;
    e.res.stop();
    entries.delete(window);
    statsFeedState.version = ++versionCounter;
    if (entries.size === 0) {
      visibleOff?.();
      visibleOff = null;
    }
  };
}
