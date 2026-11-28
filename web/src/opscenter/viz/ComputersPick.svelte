<script lang="ts">
  import type { ChartConfig } from '../cells/analytics/types';
  import { analytics } from '../cells/analytics/state.svelte';
  import { selfHostInstallId } from '../cells/analytics/host-id.svelte';
  import { explicitHostId, matchesHostFilter } from './plan';
  import { t } from '../../lib/i18n/index.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';

  let { config, edit }: { config: ChartConfig; edit: (next: Partial<ChartConfig>) => void } = $props();
  const selfId = $derived(selfHostInstallId());
  const computers = $derived((analytics.dimensions.host ?? []).filter((item) => item.filter_value));
  const canonicalId = (raw: string): string => explicitHostId(raw, selfId) ?? raw;
  const picked = $derived(config.filters?.hosts ?? computers.map((item) => canonicalId(item.filter_value as string)));

  function toggle(id: string, on: boolean): void {
    const target = canonicalId(id);
    const current = [...new Set(picked.map((host) => canonicalId(host)))];
    const next = on
      ? (current.includes(target) ? current : [...current, target])
      : current.filter((host) => host !== target);
    if (!next.length) return;
    const all = computers.every((item) => matchesHostFilter(next, item.filter_value as string, selfId));
    edit({ filters: { ...config.filters, hosts: all ? undefined : next } });
  }
</script>

{#if computers.length > 1}
  <span data-computers-pick="">{t('analytics.computers')}</span>
  {#each computers as item (item.key)}
    <Checkbox label={item.label} checked={matchesHostFilter(picked, item.filter_value as string, selfId)} onchange={(event) => toggle(item.filter_value as string, event.currentTarget.checked)} />
  {/each}
{/if}
