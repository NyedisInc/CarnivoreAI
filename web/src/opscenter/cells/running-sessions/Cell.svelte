<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const RUNNING_SESSIONS_WIDGET = defineWidget({ id: 'core.running-sessions', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* running sessions */
  import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import { elapsed, relative, leftTruncate } from '../../lib/format';
  import { clock } from '../../lib/frozen-clock.svelte';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { IconButton } from '../../../lib/base';
  import SortControl from '../../ui/SortControl.svelte';
  import StatusPill from '../../ui/StatusPill.svelte';
  import SessionFace from '../../../lib/sessions/SessionFace.svelte';
  import SubagentBadge from '../../../lib/subagents/SubagentBadge.svelte';
  import TimerBadge from '../../../lib/timers/TimerBadge.svelte';
  import { runningTotal } from '../../../lib/subagents/subagents';
  import { showsStatusLight } from '../../../lib/sessions/agent-marks';
  import {
    sessions,
    asleep,
    wakeOrPick,
    projects,
    statusLabel,
    statusHue,
    openSession,
    startSessionInProject,
    startNewProject,
    normalizeStatus,
    elapsedSeconds,
    type SessionInfo,
  } from '../../api';
  import { hostOffline, usageLimitLabel } from '../../../lib/led';
  import { hueDotToken, hueLabelToken } from '../../lib/status-hue-tokens';
  import { columnsFor, phoneColumns, phoneElapsed, taskFor } from './meta';
  import { projectFor, majorityProject } from './project';
  import { asleepRows, isAsleepRow } from './asleep';
  import { runningSessionsSortPref, sortRows, SORT_KEYS } from './sort.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import { menuActions, sortActions } from '../../widgets/menu/header-actions';
  import CascadeMenu from '../../../lib/drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

  let props: CellProps = $props();
  const { meta } = $derived(props);
  const limit = $derived(props.limit ?? null);
  const phone = $derived(props.phone ?? false);

  const widget = useWidget(RUNNING_SESSIONS_WIDGET, () => props);

  let newAnchor = $state<HTMLElement | null>(null);
  const newMenu = $derived<MenuNode[]>([
    { id: 'session', label: t('opscenter.session.new.session'), run: () => void startSessionInProject() },
    { id: 'project', label: t('opscenter.session.new.project'), run: () => void startNewProject() },
  ]);

  const sortLabel = $derived(t(`opscenter.session.sort.${runningSessionsSortPref.value}`));
  const sortMenu = $derived<MenuNode[]>(
    SORT_KEYS.map((key) => ({
      id: key,
      label: t(`opscenter.session.sort.${key}`),
      run: () => runningSessionsSortPref.set(key),
    })),
  );

  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const showAgentName = $derived(atLeast(meta.widthStates, widthState, 'agent-name'));
  const showStatusLabel = $derived(atLeast(meta.widthStates, widthState, 'status-label'));
  const columns = $derived(phone ? phoneColumns() : columnsFor(widthState));

  const frozenAt = clock.frozen ? Date.now() : null;
  const nowMs = $derived.by(() => {
    void clock.now;
    return frozenAt ?? Date.now();
  });

  interface RowPlan {
    rows: number;
    head: boolean;
    detail: boolean;
  }
  function rowPlanFor(state: string): RowPlan {
    switch (state) {
      case 'rows-bare':
        return { rows: 2, head: false, detail: false };
      case 'rows':
        return { rows: 2, head: true, detail: false };
      case 'rows-3':
        return { rows: Infinity, head: true, detail: false };
      case 'rows-detail':
        return { rows: Infinity, head: true, detail: true };
      default:
        return { rows: 0, head: false, detail: false };
    }
  }
  const plan = $derived(rowPlanFor(heightState));

  const liveRows = $derived((sessions.data ?? []) as SessionInfo[]);
  const subagentTotal = $derived(runningTotal(liveRows));
  const projectRows = $derived(projects.data ?? []);
  const majority = $derived(majorityProject(liveRows.map((row) => row.session.working_dir), projectRows));

  const liveOrdered = $derived(sortRows(liveRows, runningSessionsSortPref.value, projectRows, nowMs));

  const orderedRows = $derived.by(() => {
    const liveNames = new Set(liveRows.map((row) => row.tmux_session).filter((n): n is string => !!n));
    return [...liveOrdered, ...asleepRows(asleep.data ?? [], liveNames)];
  });

  let wakeNotice = $state<string | null>(null);

  async function wake(row: SessionInfo): Promise<void> {
    if (!isAsleepRow(row)) return;
    wakeNotice = null;
    try {
      const name = row.tmux_session ?? '';
      const result = await wakeOrPick(row.session_uuid, name, taskFor(row));
      if (result && result.status !== 'started') {
        wakeNotice = t('session.wake.failed', { name: taskFor(row), reason: result.detail });
      }
    } catch (err) {
      wakeNotice = t('session.wake.failed', { name: taskFor(row), reason: (err as Error).message });
    }
    await Promise.all([asleep.refresh(), sessions.refresh()]);
  }

  const shownRows = $derived(orderedRows.slice(0, limit ?? plan.rows) as unknown as Record<string, unknown>[]);

  function rowKey(row: Record<string, unknown>): string {
    const info = row as unknown as SessionInfo;
    return info.session.id;
  }

  function agentFor(row: SessionInfo): string {
    return row.session.model ?? row.agent_wrapper_label ?? row.agent_family ?? t('opscenter.value.unknown');
  }

  function detailFor(row: SessionInfo): string {
    const source = row.status_source ?? t('opscenter.value.not_measured');
    const dir = leftTruncate(row.session.working_dir, 28);
    const lastSeconds = elapsedSeconds(row.session.last_activity, nowMs);
    const lastText =
      lastSeconds === null ? t('opscenter.value.not_measured') : relative(Math.floor(lastSeconds / 60));
    return t('opscenter.session.detail', { source, dir, last: lastText });
  }

  function isHollow(row: SessionInfo): boolean {
    if (row.startup_gate === 'awaiting_startup_prompt') return false;
    const key = normalizeStatus(row.activity_status);
    if (row.unread === true && (key === 'idle' || key === 'unknown')) return true;
    return key === 'unknown';
  }

  const frameHeader = $derived(widget.frame);
  $effect(() => (frameHeader ? declareWidgetActions(frameHeader.hostId, 'sort', sortActions(sortMenu)) : undefined));
  $effect(() =>
    frameHeader ? declareWidgetActions(frameHeader.hostId, 'new', menuActions(newMenu, 'new:', (node) => node.label)) : undefined,
  );
</script>

{#snippet headerControls()}
  
  <span class="oc-frame-extra">
    <SubagentBadge
      running={subagentTotal}
      rollup
      rollupTitle={t('subagents.total.title', { count: subagentTotal })}
    />
  </span>
  <SortControl
    buttonText={t('opscenter.session.sort.button', { label: sortLabel })}
    menuLabel={t('opscenter.session.sort.menu')}
    menu={sortMenu}
  />
  <span class="oc-new-wrap">
    <span class="oc-new">
      <IconButton label={t('opscenter.session.new.button')} variant="quiet" icon="plus" iconSize={15} aria-haspopup="menu" aria-expanded={newAnchor !== null}
        data-oc-new onclick={(event) => (newAnchor = newAnchor ? null : (event.currentTarget as HTMLElement))} />
    </span>
    {#if newAnchor}
      <CascadeMenu root={newMenu} anchor={newAnchor} label={t('opscenter.session.new.menu')} onClose={() => (newAnchor = null)} />
    {/if}
  </span>
{/snippet}

<WidgetShell {widget} controls={headerControls}>
<ShellScroll>
{#if sessions.status === 'loading'}
  <DataTable {columns} rows={[]} showHead rowHeight={37} headHeight={33} rowKey={() => ''}>
    {#snippet cell()}{/snippet}
  </DataTable>
  <State kind="loading" inline title={t('opscenter.session.loading')} />
{:else if sessions.status === 'signed-out'}
  <State inline title={t('opscenter.session.signed_out')} />
{:else if sessions.status === 'error' || sessions.status === 'unavailable'}
  <State kind="error" inline title={sessions.error ?? ''} />
{:else}
  <DataTable
    {columns}
    rows={shownRows}
    showHead={!phone && plan.head}
    compact={phone}
    rowHeight={plan.detail ? 42 : 37}
    headHeight={33}
    {rowKey}
    rowIdAttr="data-session-id"
    onActivate={(row) => {
      const info = row as unknown as SessionInfo;
      if (isAsleepRow(info)) void wake(info);
      else openSession(info.session.id, info.tmux_session);
    }}
    rowLabel={(row) => {
      const info = row as unknown as SessionInfo;
      return t(isAsleepRow(info) ? 'opscenter.session.wake_row' : 'opscenter.session.open_row', {
        name: taskFor(info),
      });
    }}
  >
    {#snippet cell(rawRow, column, index)}
      {@const row = rawRow as unknown as SessionInfo}
      {#if column.key === 'id'}
        {index + 1}
      {:else if column.key === 'task'}
        <span class="oc-task">
          <span class="oc-task-name" class:oc-task-strong={phone}>{taskFor(row)}</span>
          {#if plan.detail && !phone}
            <span class="oc-task-detail">{detailFor(row)}</span>
          {/if}
        </span>
      {:else if column.key === 'agent'}
        {#if showAgentName}
          <span class="oc-agent-name">{agentFor(row)}</span>
        {:else}
          <span class="oc-agent-icon">
            <Icon name="bot" size={14} />
            <span class="oc-visually-hidden">{agentFor(row)}</span>
          </span>
        {/if}
      {:else if column.key === 'project'}
        {@const name = projectFor(row.session.working_dir, projectRows)}
        
        <span class="oc-project" class:oc-project-link={!phone && name !== majority}>{name}</span>
      {:else if column.key === 'elapsed'}
        {@const seconds = elapsedSeconds(row.session.created_at, nowMs)}
        {#if phone}
          
          <span class="oc-elapsed-compact" data-live-clock
            >{phoneElapsed(seconds)}{#if seconds === null}<span class="oc-visually-hidden"
                >{t('opscenter.value.not_measured')}</span
              >{/if}</span
          >
        {:else}
          <span data-live-clock
            >{seconds === null ? t('opscenter.value.not_measured') : elapsed(seconds)}</span
          >
        {/if}
      {:else if column.key === 'status' && !showsStatusLight(row.agent_family)}
        
      {:else if column.key === 'status' && isAsleepRow(row)}
        
        {@const asleepLabel = t(row.unread === true ? 'session.asleep.label_unread' : 'session.asleep.label')}
        <span class="oc-status oc-asleep-mark">
          <SessionFace {row} lifecycle="asleep" size="9px" />
          {#if showStatusLabel && !phone}
            <span class="oc-status-label">{asleepLabel}</span>
          {:else}
            <span class="oc-visually-hidden">{asleepLabel}</span>
          {/if}
        </span>
      {:else if column.key === 'status'}
        {@const hue = statusHue(row.activity_status, row.startup_gate, row.unread, hostOffline(row), usageLimitLabel(row))}
        {@const hollow = isHollow(row)}
        {@const text = statusLabel(row.activity_status, row.startup_gate, row.unread, hostOffline(row), row.activity_hint, usageLimitLabel(row))}
        {#if phone}
          
          <StatusPill
            dot
            tone={hueDotToken(hue)}
            shape={hollow ? 'hollow' : 'solid'}
            label={text}
          />
          <SubagentBadge running={row.subagents_running} total={row.subagents_total}
            sessionId={row.session.id} name={taskFor(row)} />
          <TimerBadge live={row.timers_live} nextFireAt={row.timers_next_fire_at}
            sessionId={row.session.id} name={taskFor(row)} />
        {:else}
        <span class="oc-status">
          <span
            class="oc-status-dot"
            class:oc-status-dot-hollow={hollow}
            style={`--oc-dot-color:${hueDotToken(hue)}`}
          ></span>
          {#if showStatusLabel}
            <span class="oc-status-label" style={`color:${hueLabelToken(hue)}`}>{text}</span>
          {:else}
            <span class="oc-visually-hidden">{text}</span>
          {/if}
          
          <SubagentBadge running={row.subagents_running} total={row.subagents_total}
            sessionId={row.session.id} name={taskFor(row)} />
          <TimerBadge live={row.timers_live} nextFireAt={row.timers_next_fire_at}
            sessionId={row.session.id} name={taskFor(row)} />
        </span>
        {/if}
      {/if}
    {/snippet}
  </DataTable>
  {#if wakeNotice}<State inline title={wakeNotice} />{/if}
{/if}
</ShellScroll>
</WidgetShell>

<style>
  .oc-visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }


  .oc-task {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: var(--oc-space-0-5);
  }

  .oc-task-name {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .oc-task-strong {
    font-weight: 600;
    color: var(--oc-text-primary);
  }

  .oc-elapsed-compact {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .oc-task-detail {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: var(--oc-fs-micro);
    color: var(--oc-text-dim);
  }

  .oc-agent-icon,
  .oc-agent-name {
    display: inline-flex;
    align-items: center;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .oc-project {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .oc-project-link {
    color: var(--oc-cyan);
  }

  .oc-status {
    display: inline-flex;
    align-items: center;
    gap: calc(var(--oc-space-1-5) + var(--oc-border));
    min-width: 0;
  }

  .oc-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: 0 0 auto;
    background: var(--oc-dot-color);
  }

  .oc-status-dot-hollow {
    background: transparent;
    box-shadow: inset 0 0 0 1.5px var(--oc-dot-color);
  }

  :global([data-session-id^='asleep:']) {
    opacity: 0.5;
  }

  .oc-asleep-mark {
    color: var(--oc-text-dim);
  }

  .oc-status-label {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }


  .oc-new-wrap {
    position: relative;
    display: inline-flex;
    flex: 0 0 auto;
  }

  .oc-new {
    display: inline-flex;
    margin-left: var(--oc-space-1);
  }
</style>
