<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const SCHEDULED_TASKS_WIDGET = defineWidget({ id: 'core.scheduled-tasks', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import {
    acquireScheduledTasks,
    releaseScheduledTasks,
    type ScheduledTaskRow,
    type ScheduledTasksList,
  } from '../../api/scheduled-tasks.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { relative } from '../../lib/format';
  import { columns, COLUMNS_AT, phoneColumns } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  type Row = ScheduledTaskRow & Record<string, unknown>;

  let props: CellProps = $props();
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(SCHEDULED_TASKS_WIDGET, () => props);
  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);
  let tasks = $state.raw<Resource<ScheduledTasksList> | null>(null);

  $effect(() => {
    tasks = untrack(() => acquireScheduledTasks());
    return () => {
      tasks = null;
      untrack(() => releaseScheduledTasks());
    };
  });

  const shownColumns = $derived.by((): ColumnSpec[] => {
    if (phone) return phoneColumns;
    const keys = COLUMNS_AT[widthState] ?? COLUMNS_AT['name'] ?? [];
    return keys.map((key) => columns.find((column) => column.key === key)).filter((column): column is ColumnSpec => Boolean(column));
  });

  const showHead = $derived(!phone && heightState === 'rows');
  const showBody = $derived(phone || heightState !== 'title');

  const notice = $derived.by((): string => {
    if (!tasks || tasks.status === 'loading') return t('opscenter.scheduled_tasks.loading');
    if (tasks.status === 'signed-out') return t('opscenter.scheduled_tasks.signed_out');
    if (tasks.status === 'unavailable') return t('opscenter.scheduled_tasks.unavailable');
    if (tasks.status === 'error') return tasks.error ?? t('opscenter.scheduled_tasks.error');
    const data = tasks.data;
    if (!data) return t('opscenter.scheduled_tasks.error');
    if (data.state === 'absent') return t('opscenter.scheduled_tasks.absent');
    if (data.state === 'unreadable') return t('opscenter.scheduled_tasks.unreadable');
    if (data.tasks.length === 0) return t('opscenter.scheduled_tasks.empty');
    return '';
  });

  const rows = $derived.by((): ScheduledTaskRow[] =>
    tasks && tasks.status === 'ok' && tasks.data && tasks.data.state === 'ok' ? tasks.data.tasks : [],
  );
  const hidden = $derived(tasks?.data && tasks.data.truncated ? tasks.data.total - tasks.data.tasks.length : 0);

  function lastRun(row: ScheduledTaskRow): string {
    if (!row.last_run_at) return t('opscenter.scheduled_tasks.never_run');
    const at = Date.parse(row.last_run_at);
    if (!Number.isFinite(at)) return t('opscenter.scheduled_tasks.never_run');
    return relative((Date.now() - at) / 60000);
  }
</script>

{#snippet rowCell(row: Row, column: ColumnSpec, _index: number)}
  {#if column.key === 'name'}
    {@const shown = row.host_label ? `${row.name} @ ${row.host_label}` : row.name}
    <span class="oc-st-name">
      <span class="oc-st-icon"><Icon name="clock" size={12} /></span>
      <span class="oc-st-name-text">{shown}</span>
    </span>
  {:else if column.key === 'description'}
    <span class="oc-st-description">
      {row.description ?? t('opscenter.scheduled_tasks.no_description')}
    </span>
  {:else if column.key === 'schedule'}
    {#if row.schedule}
      <span class="oc-st-schedule">{row.schedule}</span>
    {:else}
      <span class="oc-st-muted">
        {t('opscenter.scheduled_tasks.not_recorded')}
      </span>
    {/if}
  {:else if column.key === 'lastRun'}
    <span class="oc-st-muted">
      {lastRun(row)}
    </span>
  {/if}
{/snippet}

<WidgetShell {widget}>
<ShellScroll>
{#if showBody}
  {#if notice}
    <State inline kind={stateKindOf(tasks?.status)} data-scheduled-tasks-notice title={notice} />
  {:else}
    <DataTable
      columns={shownColumns}
      rows={(limit === null ? rows : rows.slice(0, limit)) as Row[]}
      rowHeight={28}
      headHeight={27}
      {showHead}
      compact={phone}
      rowKey={(row) => `${row.host_key ?? 'local'}:${row.id}`}
      cell={rowCell}
    />
    {#if hidden > 0}
      <State inline title={t('opscenter.scheduled_tasks.truncated', { count: hidden })} />
    {/if}
  {/if}
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-st-name {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      overflow: hidden;
    }

    .oc-st-icon {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      justify-content: center;
      color: var(--oc-cyan);
    }

    .oc-st-name-text,
    .oc-st-description {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .oc-st-name-text {
      color: var(--oc-text-bright);
    }

    .oc-st-description {
      display: block;
      color: var(--oc-text-secondary);
    }

    .oc-st-schedule {
      color: var(--oc-text-primary);
      font-variant-numeric: tabular-nums;
    }

    .oc-st-muted {
      color: var(--oc-text-dim);
      white-space: nowrap;
    }

  }
</style>
