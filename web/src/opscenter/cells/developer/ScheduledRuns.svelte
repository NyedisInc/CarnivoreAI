<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import RunChartTable from '../../ui/RunChartTable.svelte';
  import ScopeFilter from '../../ui/ScopeFilter.svelte';
  import { readScope, writeScope, type Scope } from '../../ui/scope-filter';
  import type { ColumnSpec } from '../../engine/types';
  import { t } from '../../../lib/i18n/index.svelte';
  import { taskManagerAddonOn } from '../../../lib/task-manager-schedules/task-manager-addon.svelte';
  import type { TaskManagerSchedule } from '../../../lib/task-manager-schedules/task-manager-scheduled';
  import {
    acquireTaskManagerSchedules,
    acquireScheduledRuns,
    releaseTaskManagerSchedules,
    releaseScheduledRuns,
    type ScheduledRuns,
  } from '../../api/scheduled-runs.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { agoWords, columnsFor, nextWords, runTimeWords } from '../../lib/run-chart';
  import { MARK_KEYS, SCHEDULED_COLUMNS, scheduledChart, type ScheduledRow } from './model';
  import RunQueue from '../../ui/RunQueue.svelte';
  import { scheduledQueue, scheduledRunning, type ActivityInput } from './activity';

  let { width, phone = false, limit = null }: CellProps = $props();

  const SCOPE_SURFACE = 'developer-scheduled';

  let scope = $state<Scope>(readScope(SCOPE_SURFACE));
  let feed = $state.raw<Resource<ScheduledRuns> | null>(null);
  let huddle = $state.raw<Resource<TaskManagerSchedule[]> | null>(null);

  $effect(() => {
    feed = untrack(() => acquireScheduledRuns());
    return () => {
      untrack(() => releaseScheduledRuns());
      feed = null;
    };
  });

  const taskManagerOn = $derived(taskManagerAddonOn());
  const wantsTaskManager = $derived(taskManagerOn && scope !== 'global');

  $effect(() => {
    if (!wantsTaskManager) return;
    huddle = untrack(() => acquireTaskManagerSchedules());
    return () => {
      untrack(() => releaseTaskManagerSchedules());
      huddle = null;
    };
  });

  $effect(() => startClock());

  const nowMs = $derived.by(() => {
    void clock.now;
    return Date.now();
  });

  const input = $derived<ActivityInput>({
    automations: feed?.data?.automations ?? [],
    runs: feed?.data?.runs ?? [],
    projects: feed?.data?.projects ?? {},
    huddle: wantsTaskManager ? (huddle?.data ?? []) : [],
  });
  const rows = $derived(scheduledChart(input, nowMs, scope));
  const running = $derived(scheduledRunning(input, nowMs / 1000, scope, t));
  const queue = $derived(scheduledQueue(input, nowMs / 1000, scope, t));
  const shownColumns = $derived<ColumnSpec[]>(columnsFor(SCHEDULED_COLUMNS, width, phone));
  const needed = $derived<(Resource<unknown> | null)[]>([
    ...(scope !== 'sessions' ? [feed] : []),
    ...(wantsTaskManager ? [huddle] : []),
  ]);
  const view = $derived<'loading' | 'unknown' | 'ready'>(viewOf(needed));
  const partial = $derived(view === 'ready' && needed.some((read) => readState(read) === 'failed'));

  function readState(read: Resource<unknown> | null): 'loading' | 'failed' | 'ready' {
    if (read?.data) return 'ready';
    return read && read.status !== 'loading' ? 'failed' : 'loading';
  }

  /* there is nothing */
  function viewOf(reads: readonly (Resource<unknown> | null)[]): 'loading' | 'unknown' | 'ready' {
    const states = reads.map(readState);
    if (states.length === 0 || states.includes('ready')) return 'ready';
    return states.every((state) => state === 'failed') ? 'unknown' : 'loading';
  }

  function pick(next: Scope): void {
    scope = next;
    writeScope(SCOPE_SURFACE, next);
  }

  function areaWords(row: ScheduledRow): string {
    if (row.area) return row.area;
    return row.shared ? t('opscenter.chart.shared') : t('pipeline.chart.machine');
  }
</script>

{#snippet rowCell(row: ScheduledRow, column: ColumnSpec, _index: number)}
  {#if column.key === 'name'}
    <span class="oc-rc-name">
      <span class="oc-rc-mark" data-mark={row.mark} title={t(MARK_KEYS[row.mark])} aria-hidden="true"></span>
      <bdi class="oc-rc-name-text">{row.name}</bdi>
      <span class="oc-visually-hidden" data-outcome-words>{t(MARK_KEYS[row.mark])}</span>
    </span>
  {:else if column.key === 'by'}
    <span class="oc-rc-area" data-by>{row.by ? t(row.by.key, row.by.params) : ''}</span>
  {:else if column.key === 'area'}
    <bdi class="oc-rc-area">{areaWords(row)}</bdi>
  {:else if column.key === 'runTime'}
    <span class="oc-rc-muted">{row.runSeconds === null ? '' : runTimeWords(row.runSeconds * 1000)}</span>
  {:else if column.key === 'ago'}
    <span class="oc-rc-muted">{row.mark === 'running' ? t('opscenter.chart.running') : agoWords(row.agoSeconds)}</span>
  {:else if column.key === 'next'}
    <span class="oc-rc-muted">{row.paused ? t('opscenter.chart.paused') : nextWords(row.nextSeconds)}</span>
  {/if}
{/snippet}

<div class="oc-rc" data-scheduled-monitor data-view={view} data-scheduled-scope={scope}>
  <div class="oc-rc-bar">
    <ScopeFilter value={scope} onChange={pick} label={t('opscenter.scope.label')} />
  </div>
  {#if view === 'ready'}
    <RunQueue running={running} queue={queue.shown} more={queue.more} queued={queue.shown.length + queue.more} />
    {#if rows.length > 0}
      <div data-scheduled-chart>
        <RunChartTable columns={shownColumns} {rows} {limit} {phone} cell={rowCell} />
      </div>
    {:else if !(scope === 'sessions' && !taskManagerOn) && !partial}
      <p class="oc-rc-notice" data-scheduled-none>{t('opscenter.cell.developer.none')}</p>
    {/if}
    {#if scope !== 'global' && !taskManagerOn}
      <p class="oc-rc-notice" data-scheduled-huddle-off>{t('opscenter.chart.task_manager_off')}</p>
    {/if}
    {#if partial}
      <p class="oc-rc-notice" data-scheduled-note="unknown" data-tone="bad" role="status">{t('opscenter.cell.developer.unknown')}</p>
    {/if}
  {:else}
    <p class="oc-rc-notice" data-scheduled-note={view} data-tone={view === 'unknown' ? 'bad' : undefined} role="status">{t(`opscenter.cell.developer.${view}`)}</p>
  {/if}
</div>
