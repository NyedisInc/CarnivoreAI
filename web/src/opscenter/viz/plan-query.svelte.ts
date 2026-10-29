import type { QueryBody } from '../cells/analytics/types';
import { t } from '../../lib/i18n/index.svelte';
import { runQueries, type BatchItem } from './query-client';

export interface Plan {
  on: boolean;
  items: QueryBody[];
  tick?: number;
}

const FOLLOW_UPS = 3;
const FOLLOW_UP_MS = 2000;

export function planQuery(read: () => Plan, visible: () => boolean): { readonly outcomes: BatchItem[] | null; readonly failure: string } {
  let outcomes = $state<BatchItem[] | null>(null);
  let failure = $state('');
  let again = $state(0);
  let followUps = 0;
  const key = $derived(JSON.stringify(read()));
  $effect(() => {
    void again;
    const plan = JSON.parse(key) as Plan;
    if (!plan.on || plan.items.length === 0) { outcomes = null; failure = ''; return; }
    if (!visible()) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    runQueries(plan.items, abort.signal).then((next) => {
      failure = ''; outcomes = next;
      if (next.some((item) => item.ok && item.answer?.reason === 'refreshing') && followUps < FOLLOW_UPS) {
        followUps += 1;
        timer = setTimeout(() => { again += 1; }, FOLLOW_UP_MS);
      } else followUps = 0;
    })
      .catch((cause: unknown) => { if (!abort.signal.aborted) failure = cause instanceof Error ? cause.message : t('analytics.query_failed'); });
    return () => { abort.abort(); if (timer !== null) clearTimeout(timer); };
  });
  return { get outcomes() { return outcomes; }, get failure() { return failure; } };
}
