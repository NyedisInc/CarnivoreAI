<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const SKILLS_WIDGET = defineWidget({ id: 'core.skills', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import { onMount } from 'svelte';
  import { catalog, byKind, refreshCatalogOnOpen, type CatalogItemView } from '../../api';
  import { columns, COLUMNS_AT, phoneColumns } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  type Row = CatalogItemView & Record<string, unknown>;

  let props: CellProps = $props();
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(SKILLS_WIDGET, () => props);

  onMount(() => {
    void refreshCatalogOnOpen();
  });

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

  const notice = $derived.by((): string => {
    if (catalog.status === 'signed-out') return t('opscenter.skills.signed_out');
    if (catalog.status === 'unavailable') return t('opscenter.skills.unavailable');
    if (catalog.status === 'error') return catalog.error ?? t('opscenter.skills.error');
    return '';
  });

  const rows = $derived.by((): CatalogItemView[] => (catalog.status === 'ok' ? byKind(catalog.data, 'skill') : []));
  const untrustedRows = $derived.by((): CatalogItemView[] =>
    catalog.status === 'ok' && catalog.data ? catalog.data.untrusted.filter((item) => item.kind === 'skill') : [],
  );
  function description(item: CatalogItemView): string {
    const brief = (item.card as Record<string, unknown> | undefined)?.['brief'];
    return typeof brief === 'string' ? brief : '';
  }

  function detailFor(row: Row): string {
    const shown = new Set(shownColumns.map((column) => column.key));
    const parts: string[] = [];
    if (!shown.has('author')) parts.push(row.publisher);
    if (!shown.has('version')) parts.push(row.latest);
    return parts.join(t('opscenter.list.separator'));
  }
</script>

{#snippet rowCell(row: Row, column: ColumnSpec, _index: number)}
  {#if column.key === 'name'}
    <span class="oc-skill-cell">
      <span class="oc-skill-name">
        <span class="oc-row-icon oc-row-icon--tile">
          <Icon name="skill" size={12} />
        </span>
        <span class="oc-skill-name-text">{row.name}</span>
        {#if row.installed}
          <span class="oc-installed" title={t('opscenter.skills.installed')}>
            <Icon name="check" size={10} />
          </span>
        {/if}
      </span>
      {#if showDetail && detailFor(row)}
        <span class="oc-detail">{detailFor(row)}</span>
      {/if}
    </span>
  {:else if column.key === 'description'}
    {description(row)}
  {:else if column.key === 'author'}
    <span class="oc-muted">{row.publisher}</span>
  {:else if column.key === 'version'}
    <span class="oc-muted">{row.latest}</span>
  {/if}
{/snippet}

<WidgetShell {widget}>
<ShellScroll>
{#if showBody}
  <DataTable
    columns={shownColumns}
    rows={(limit === null ? rows : rows.slice(0, limit)) as Row[]}
    {rowHeight}
    headHeight={27}
    showHead={showHead}
    compact={phone}
    rowKey={(row) => row.id}
    cell={rowCell}
  />
  {#if phone || showHead}
    {#if notice}
      <State inline kind={stateKindOf(catalog.status)} title={notice} />
    {:else if catalog.status === 'ok'}
      {#if untrustedRows.length}
        <p class="oc-divider">{t('opscenter.skills.untrusted')}</p>
        <DataTable
          columns={shownColumns}
          rows={untrustedRows as Row[]}
          rowHeight={rowHeight}
          headHeight={27}
          showHead={false}
          compact={phone}
          rowKey={(row) => row.id}
          cell={rowCell}
        />
      {/if}
    {/if}
  {/if}
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-skill-cell {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--oc-space-0-5);
      min-width: 0;
      overflow: hidden;
    }

    .oc-skill-name {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      overflow: hidden;
    }

    .oc-skill-name-text {
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
    }

    .oc-row-icon--tile {
      width: 20px;
      height: 20px;
      border-radius: var(--oc-radius-sm);
      border: 1px solid currentColor;
      color: var(--oc-orange);
    }

    .oc-installed {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      justify-content: center;
      color: var(--oc-green-bright);
    }

    .oc-detail {
      display: block;
      margin-top: var(--oc-space-0-5);
      padding-left: calc(var(--oc-space-5) + var(--oc-space-1));
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-muted {
      color: var(--oc-text-secondary);
    }


                .oc-divider {
      margin: 0;
      padding: var(--oc-space-1-5) var(--oc-space-3) var(--oc-space-0-5);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-dim);
    }
  }
</style>
