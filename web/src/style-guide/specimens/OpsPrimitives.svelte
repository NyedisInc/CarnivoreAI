<script lang="ts">
  import StatusPill from '../../opscenter/ui/StatusPill.svelte';
  import AgentTier from '../../opscenter/ui/AgentTier.svelte';
  import Sparkline from '../../opscenter/ui/Sparkline.svelte';
  import SortControl from '../../opscenter/ui/SortControl.svelte';
  import DataTable from '../../opscenter/ui/DataTable.svelte';
  import type { ColumnSpec } from '../../opscenter/engine/types';
  import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../lib/i18n/index.svelte';

  let { part }: { part: 'pills' | 'spark' | 'sort' | 'table' } = $props();

  let sortBy = $state('recent');
  let picked = $state<string | null>(null);

  const sortMenu = $derived<MenuNode[]>(
    ['recent', 'name', 'status'].map((key) => ({
      id: key,
      label: key,
      checked: sortBy === key,
      run: () => {
        sortBy = key;
      },
    })),
  );

  const columns: ColumnSpec[] = [
    { key: 'name', headKey: 'opscenter.column.account', minPx: 140, weight: 2, insetPx: 12 },
    { key: 'provider', headKey: 'opscenter.column.provider', minPx: 84, weight: 1, insetPx: 10 },
    { key: 'plan', headKey: 'opscenter.column.plan', minPx: 66, weight: 1, insetPx: 10 },
    { key: 'resets', headKey: 'opscenter.column.resets', minPx: 88, weight: 1, insetPx: 10, align: 'end' },
  ];

  const rows: Record<string, unknown>[] = [
    { name: 'personal', provider: 'claude', plan: 'max', resets: '2h 10m' },
    { name: 'work', provider: 'codex', plan: 'pro', resets: '5d' },
    { name: 'spare', provider: 'claude', plan: 'pro', resets: 'unknown' },
  ];

</script>

{#if part === 'pills'}
  <div class="sg-row">
    <StatusPill label="running" tone="var(--oc-green)" dot={true} />
    <StatusPill label="waiting" tone="var(--oc-yellow)" dot={true} />
    <StatusPill label="notice" tone="var(--oc-cyan)" dot={true} />
    <StatusPill label="not measured" tone="var(--oc-text-muted)" dot={true} shape="hollow" />
    <StatusPill label="failed" tone="var(--oc-coral)" />
    <StatusPill label="dot only" tone="var(--oc-green)" dot={true} showLabel={false} />
  </div>
  <div class="sg-row">
    <AgentTier name="claude" />
    <AgentTier name="codex" />
    <AgentTier name="shell" showName={false} />
  </div>
{:else if part === 'spark'}
  <div class="sg-row">
    <Sparkline values={[2, 4, 3, 6, 8, 5, 9, 7, 10, 6, 4, 8]} />
    <Sparkline values={[1, 1, 2, 1, 3, 2, 2, 4, 3, 5]} tone="var(--oc-spark-mid)" height={30} gap={3} barWidth={4} />
    <Sparkline
      bars={[
        { h: 6, tone: 'var(--oc-spark-dim)' },
        { h: 14, tone: 'var(--oc-spark)' },
        { h: 10, tone: 'var(--oc-spark-mid)' },
        { h: 20, tone: 'var(--oc-spark)' },
        { h: 4, tone: 'var(--oc-spark-dim)' },
      ]}
    />
  </div>
{:else if part === 'sort'}
  <SortControl
    buttonText={t('opscenter.session.sort.button', { label: sortBy })}
    menuLabel={t('opscenter.session.sort.menu')}
    menu={sortMenu}
  />
{:else if part === 'table'}
  <div class="sg-table-host">
    <DataTable
      {columns}
      {rows}
      rowKey={(row) => String(row.name)}
      onActivate={(row) => (picked = String(row.name))}
      rowLabel={(row) => `open ${String(row.name)}`}
    >
      {#snippet cell(row, col)}
        <span>{String(row[col.key] ?? '')}</span>
      {/snippet}
    </DataTable>
  </div>
  <p class="sg-caption">activated row: <code>{picked ?? 'none yet, press enter on a row'}</code></p>
{/if}
