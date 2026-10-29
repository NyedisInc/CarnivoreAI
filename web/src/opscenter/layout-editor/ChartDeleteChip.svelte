<script lang="ts">
  import { onDestroy } from 'svelte';
  import { deleteSavedChart, tripwireCountFor } from '../cells/analytics/delete-chart';
  import { t } from '../../lib/i18n/index.svelte';

  const CONFIRM_MS = 4000;

  let { chartId }: { chartId: string } = $props();

  let armed = $state(false);
  let busy = $state(false);
  let failure = $state('');
  let timer: ReturnType<typeof setTimeout> | null = null;

  const wires = $derived(armed ? tripwireCountFor(chartId) : 0);
  const label = $derived(wires > 0 ? t('analytics.delete_confirm_wires', { count: wires }) : armed ? t('analytics.delete_confirm') : t('analytics.delete'));

  function disarm(): void {
    armed = false;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  async function press(): Promise<void> {
    if (busy) return;
    if (!armed) {
      failure = '';
      armed = true;
      timer = setTimeout(disarm, CONFIRM_MS);
      return;
    }
    disarm();
    busy = true;
    try {
      await deleteSavedChart(chartId);
    } catch (error) {
      failure = error instanceof Error ? error.message : t('analytics.chart_unavailable');
    } finally {
      busy = false;
    }
  }

  onDestroy(disarm);
</script>

<button type="button" class="le-chip le-chip--danger" class:le-chip--armed={armed} data-chart-delete={chartId} title={failure || undefined} disabled={busy}
  onclick={() => void press()} onblur={disarm} onkeydown={(event) => { if (event.key === 'Escape' && armed) { event.stopPropagation(); disarm(); } }}>{label}</button>

<style>
  @layer components {
  .le-chip--danger {
    color: var(--oc-coral);
  }

  .le-chip--armed {
    border-color: var(--oc-coral);
  }
  }
</style>
