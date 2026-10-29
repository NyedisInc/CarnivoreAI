<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const PLUGINS_WIDGET = defineWidget({ id: 'core.plugins', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import { PLUGIN_REGISTRY, type PluginMirrorRow } from './registry-mirror';
  import { columns, COLUMNS_AT, phoneColumns } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import { Tag } from '../../../lib/base';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  type Row = PluginMirrorRow & Record<string, unknown>;

  let props: CellProps = $props();
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(PLUGINS_WIDGET, () => props);
  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const shownColumns = $derived.by((): ColumnSpec[] => {
    if (phone) return phoneColumns;
    const keys = COLUMNS_AT[widthState] ?? COLUMNS_AT['name'] ?? [];
    return keys.map((key) => columns.find((column) => column.key === key)).filter((column): column is ColumnSpec => Boolean(column));
  });

  const showHead = $derived(!phone && heightState !== 'title' && heightState !== 'rows-bare');
  const showBody = $derived(heightState !== 'title');
  const showDetail = $derived(!phone && heightState === 'rows-detail');
  const rowHeight = $derived(showDetail ? 40 : 28);

  function contributionsLabel(row: PluginMirrorRow): string {
    return t('opscenter.plugins.contributions', { count: row.contributionCount });
  }

  function detailFor(row: Row): string {
    const shown = new Set(shownColumns.map((column) => column.key));
    const parts: string[] = [];
    if (!shown.has('surfaces')) parts.push(row.surfaces.join(t('opscenter.list.comma')));
    if (!shown.has('contributions')) parts.push(contributionsLabel(row));
    return parts.join(t('opscenter.list.separator'));
  }
</script>

<WidgetShell {widget}>
<ShellScroll>
{#if showBody}
  <DataTable
    columns={shownColumns}
    rows={(limit === null ? PLUGIN_REGISTRY : PLUGIN_REGISTRY.slice(0, limit)) as Row[]}
    {rowHeight}
    headHeight={27}
    showHead={showHead}
    compact={phone}
    rowKey={(row) => row.id}
  >
    {#snippet cell(row: Row, column, _index)}
      {#if column.key === 'name'}
        {#if phone}
          <span class="oc-plugin-name-text">{row.id}</span>
        {:else}
          <span class="oc-plugin-cell">
            <span class="oc-plugin-name">
              <span class="oc-row-icon">
                <Icon name="cube" size={15} />
              </span>
              <span class="oc-plugin-name-text">{row.id}</span>
            </span>
            {#if showDetail && detailFor(row)}
              <span class="oc-detail">{detailFor(row)}</span>
            {/if}
          </span>
        {/if}
      {:else if column.key === 'surfaces'}
        {row.surfaces.join(t('opscenter.list.comma'))}
      {:else if column.key === 'contributions'}
        <span class="oc-muted">{row.contributionCount}</span>
      {:else if column.key === 'phoneSurface'}
        <Tag>{row.surfaces[0] ?? ''}</Tag>
      {/if}
    {/snippet}
  </DataTable>
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-plugin-cell {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--oc-space-0-5);
      min-width: 0;
      overflow: hidden;
    }

    .oc-plugin-name {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      overflow: hidden;
    }

    .oc-plugin-name-text {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-bright);
    }

    .oc-row-icon {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      justify-content: center;
      color: var(--oc-text-primary);
    }

    .oc-detail {
      display: block;
      margin-top: var(--oc-space-0-5);
      padding-left: calc(var(--oc-space-5) - var(--oc-border));
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-muted {
      color: var(--oc-text-secondary);
    }
  }
</style>
