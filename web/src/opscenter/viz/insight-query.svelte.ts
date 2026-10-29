import { untrack } from 'svelte';
import { t } from '../../lib/i18n/index.svelte';

export interface InsightRead<T> { key: string | null; fetch: (signal: AbortSignal) => Promise<T> }

export function insightRead<T>(read: () => InsightRead<T>, visible: () => boolean): { readonly data: T | null; readonly failure: string } {
  let data = $state<T | null>(null);
  let failure = $state('');
  const key = $derived(read().key);
  $effect(() => {
    if (key === null) { data = null; failure = ''; return; }
    if (!visible()) return;
    const abort = new AbortController();
    untrack(() => read().fetch)(abort.signal).then((next) => { failure = ''; data = next; })
      .catch((cause: unknown) => { if (!abort.signal.aborted) failure = cause instanceof Error ? cause.message : t('analytics.query_failed'); });
    return () => abort.abort();
  });
  return { get data() { return data; }, get failure() { return failure; } };
}
