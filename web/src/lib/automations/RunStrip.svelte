
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Mark from './Mark.svelte';
  import type { RecentRun } from './logic/types';

  let { runs, current = null }: { runs: RecentRun[]; current?: string | null } = $props();

  const strip = $derived(runs.slice(0, 12).reverse());
  const newest = $derived(runs[0]?.run_id ?? null);
  let shift = $state(false);
  let seen: string | null | undefined;

  $effect(() => {
    const now = newest;
    const calm = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (seen !== undefined && now !== seen && !calm) shift = true;
    seen = now;
  });
</script>

<span class="ap-strip-box" data-auto-strip role="img" aria-label={t('automations.page.strip.aria', { n: strip.length })}>
  {#key newest}
    <span class="ap-strip-in" data-strip-in data-n={strip.length} data-shift={shift ? '' : undefined}>
      {#each strip as run (run.run_id)}
        <i class="ap-sm" data-r={run.run_id} data-cur={current === run.run_id ? '' : undefined}><Mark status={run.status} size={8} /></i>
      {/each}
    </span>
  {/key}
</span>
