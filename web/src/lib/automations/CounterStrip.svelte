
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import { COUNTER_IDS, counterLabelKey, counterTone } from './logic/counters';
  import type { CounterId } from './logic/types';
  import { data, togglePressed } from './page-store.svelte';

  const BUMP_MS = 1300;
  let bumped = $state<Partial<Record<CounterId, boolean>>>({});
  let previous: Record<string, number> | null = null;

  $effect(() => {
    const counts = data.counts;
    if (!counts) {
      previous = null;
      return;
    }
    const next = Object.fromEntries(COUNTER_IDS.map((id) => [id, counts.counters[id]?.count ?? 0]));
    const calm = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (previous && !calm) {
      for (const id of COUNTER_IDS) {
        if (previous[id] === next[id]) continue;
        bumped[id] = true;
        setTimeout(() => (bumped[id] = false), BUMP_MS);
      }
    }
    previous = next;
  });
</script>

<div class="ap-ctb" role="toolbar" aria-label={t('automations.page.counters.aria')} data-counter-strip>
  {#each COUNTER_IDS as id (id)}
    {@const n = data.counts?.counters[id]?.count}
    {@const tone = n === undefined ? null : counterTone(id, n)}
    <Button
      variant="quiet"
      data-ct={id}
      aria-pressed={!!data.pressed[id]}
      data-tone={tone === 'coral' ? 'bad' : tone === 'yellow' ? 'wait' : undefined}
      data-bump={bumped[id] ? '' : undefined}
      onclick={() => togglePressed(id)}
    >
      <span class="ap-ct__l">{t(counterLabelKey(id))}</span>
      <span class="ap-ct__n" data-ct-n>{n === undefined ? '-' : n}</span>
    </Button>
  {/each}
</div>
