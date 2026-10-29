import { onDestroy } from 'svelte';
import { authFetch, resourcePush } from '../sdk';
import { trailPath, type TrailMessage } from './crosstalk-trail';

const FALLBACK_MS = 30000;

export function createTrailFeed(getItemId: () => number): { readonly rows: TrailMessage[] } {
  let rows = $state<TrailMessage[]>([]);
  let request = 0;

  async function load(): Promise<void> {
    const mine = ++request;
    try {
      const answer = await authFetch<{ messages: TrailMessage[] }>(trailPath(getItemId()));
      if (mine === request) rows = answer.messages ?? [];
    } catch {
      if (mine === request) rows = [];
    }
  }

  $effect(() => {
    void getItemId();
    void load();
  });

  const stop = resourcePush().pushOrPoll(() => void load(), FALLBACK_MS, ['crosstalk']);
  onDestroy(stop);
  return { get rows() { return rows; } };
}
