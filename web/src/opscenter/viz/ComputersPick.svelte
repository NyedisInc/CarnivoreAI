<script lang="ts">
  import type { ChartConfig } from '../cells/analytics/types';
  import { analytics } from '../cells/analytics/state.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';

  let { config, edit }: { config: ChartConfig; edit: (next: Partial<ChartConfig>) => void } = $props();
  const computers = $derived((analytics.dimensions.host ?? []).filter((item) => item.filter_value));
  const picked = $derived(config.filters?.hosts ?? computers.map((item) => item.filter_value as string));

  function toggle(id: string, on: boolean): void {
    const next = on ? [...picked, id] : picked.filter((host) => host !== id);
    if (!next.length) return;
    const all = computers.every((item) => next.includes(item.filter_value as string));
    edit({ filters: { ...config.filters, hosts: all ? undefined : next } });
  }
</script>

{#if computers.length > 1}
  <span data-computers-pick="">{t('analytics.computers')}</span>
  {#each computers as item (item.key)}
    <Checkbox label={item.label} checked={picked.includes(item.filter_value as string)} onchange={(event) => toggle(item.filter_value as string, event.currentTarget.checked)} />
  {/each}
{/if}
