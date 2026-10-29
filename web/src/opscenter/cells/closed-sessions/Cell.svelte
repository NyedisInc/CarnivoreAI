<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const CLOSED_SESSIONS_WIDGET = defineWidget({ id: 'core.closed-sessions', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* recently closed sessions */
  import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import { parseServerTime, relative } from '../../lib/format';
  import { clock } from '../../lib/frozen-clock.svelte';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import {
    recent,
    outcome,
    RECENT_NOTICE_KEYS,
    statusLabel,
    statusHue,
    resumeSession,
    type SessionRecord,
  } from '../../api';
  import { hueDotToken, hueLabelToken } from '../../lib/status-hue-tokens';
  import { closedSeconds, columnsFor, lifecycleIcon, phoneColumns, phoneStarted, taskFor } from './meta';
  import { closedSessionsSortPref, sortRows, SORT_KEYS } from './sort.svelte';
  import SortControl from '../../ui/SortControl.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import { sortActions } from '../../widgets/menu/header-actions';
  import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import {
    openStatusKey,
    recentOpenStatus,
    type OpenStatus,
  } from '../../../lib/launchpad/recent-open-status.svelte';

  let props: CellProps = $props();
  const { meta } = $derived(props);
  const limit = $derived(props.limit ?? null);
  const phone = $derived(props.phone ?? false);

  const widget = useWidget(CLOSED_SESSIONS_WIDGET, () => props);
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
  }
  function rowPlanFor(state: string): RowPlan {
    switch (state) {
      case 'rows-bare':
        return { rows: 3, head: false };
      case 'rows':
        return { rows: 4, head: true };
      case 'rows-5':
        return { rows: Infinity, head: true };
      case 'rows-8':
        return { rows: Infinity, head: true };
      default:
        return { rows: 0, head: false };
    }
  }
  const plan = $derived(rowPlanFor(heightState));

  const status = $derived(recent.status);
  const resultOutcome = $derived(status === 'ok' ? outcome(recent.data) : null);
  const liveRows = $derived((recent.data?.sessions ?? []) as SessionRecord[]);

  const orderedRows = $derived(sortRows(liveRows, closedSessionsSortPref.value));

  const shownRows = $derived(orderedRows.slice(0, limit ?? plan.rows) as unknown as Record<string, unknown>[]);

  function rowKey(row: Record<string, unknown>, index: number): string {
    const info = row as unknown as SessionRecord;
    return info.session_uuid || info.tmux_name || `row-${index}`;
  }

  const sortLabel = $derived(t(`opscenter.closed.sort.${closedSessionsSortPref.value}`));
  const sortMenu = $derived<MenuNode[]>(
    SORT_KEYS.map((key) => ({
      id: key,
      label: t(`opscenter.closed.sort.${key}`),
      run: () => closedSessionsSortPref.set(key),
    })),
  );

  const frameHeader = $derived(widget.frame);
  $effect(() => (frameHeader ? declareWidgetActions(frameHeader.hostId, 'sort', sortActions(sortMenu)) : undefined));

  function agentFor(row: SessionRecord): string {
    return row.agent_type ?? row.agent_family ?? t('opscenter.value.unknown');
  }

  function closedFor(row: SessionRecord): string {
    const seconds = closedSeconds(row, nowMs);
    if (seconds === null) return t('opscenter.value.not_measured');
    return relative(Math.floor(seconds / 60));
  }

  function closedTitle(row: SessionRecord): string {
    const ms = row.closed_at ? parseServerTime(row.closed_at) : NaN;
    if (!Number.isFinite(ms)) return '';
    const key = row.closed_basis === 'closed' ? 'opscenter.closed.closed_at'
      : row.closed_basis === 'added' ? 'opscenter.closed.added_at' : 'opscenter.closed.last_active_at';
    return t(key, { when: new Date(ms).toLocaleString() });
  }

  function openFor(row: SessionRecord): OpenStatus | undefined {
    return recentOpenStatus.of(openStatusKey(row.session_uuid, row.title));
  }

  function openWords(open: OpenStatus | undefined): string {
    if (!open) return '';
    if (open.phase === 'opening') return t('session.restart.pending');
    if (open.phase === 'opened') return t('session.restart.toast.opened.title');
    return t('session.restart.row_failed', { reason: open.reason });
  }
</script>

{#snippet sortControl()}
  <SortControl
    buttonText={t('opscenter.closed.sort.button', { label: sortLabel })}
    menuLabel={t('opscenter.closed.sort.menu')}
    menu={sortMenu}
  />
{/snippet}

<WidgetShell {widget} controls={sortControl}>
<ShellScroll>
<!-- running sessions -->
{#if status === 'loading'}
  <DataTable {columns} rows={[]} showHead rowHeight={26.8} headHeight={26} bodyType="oc-fs-label" headType="oc-fs-micro" rowKey={() => ''}>
    {#snippet cell()}{/snippet}
  </DataTable>
  <State kind="loading" inline title={t('opscenter.session.loading')} />
{:else if status === 'signed-out'}
  <State inline title={t('opscenter.session.signed_out')} />
{:else if status === 'error' || status === 'unavailable'}
  <State kind="error" inline title={recent.error ?? ''} />
{:else if resultOutcome === 'could-not-determine'}
  <State
    inline
    title={t(
      RECENT_NOTICE_KEYS[recent.data?.state ?? 'never_probed'] ??
        'opscenter.recent.notice.never_probed',
    )}
  />
{:else if resultOutcome === 'empty'}
  <State inline title={t('opscenter.closed.empty')} />
{:else}
  <DataTable
    {columns}
    rows={shownRows}
    showHead={!phone && plan.head}
    compact={phone}
    rowHeight={26.8}
    headHeight={26}
    bodyType="oc-fs-label"
    headType="oc-fs-micro"
    {rowKey}
    canActivate={(row) => (row as unknown as SessionRecord).lifecycle === 'stopped'}
    onActivate={(row) => {
      const record = row as unknown as SessionRecord;
      resumeSession({
        sessionUuid: record.session_uuid,
        title: record.title,
        workingDir: record.working_dir,
        agentType: record.agent_type,
      });
    }}
    rowLabel={(row) =>
      t('opscenter.closed.resume_row', { name: taskFor(row as unknown as SessionRecord) })}
  >
    {#snippet cell(rawRow, column, index)}
      {@const row = rawRow as unknown as SessionRecord}
      {@const archived = Boolean(row.archived_at)}
      {#if column.key === 'id'}
        {index + 1}
      {:else if column.key === 'task'}
        <span class="oc-task-name" class:oc-dim={archived} class:oc-task-strong={phone}
          >{taskFor(row)}</span
        >
      {:else if column.key === 'agent'}
        {#if showAgentName}
          <span class="oc-agent-name" class:oc-dim={archived}>{agentFor(row)}</span>
        {:else}
          <span class="oc-agent-icon" class:oc-dim={archived}>
            <Icon name="bot" size={14} />
            <span class="oc-visually-hidden">{agentFor(row)}</span>
          </span>
        {/if}
      {:else if column.key === 'closed'}
        {#if phone}
          {@const seconds = closedSeconds(row, nowMs)}
          
          <span
            class="oc-started-compact"
            class:oc-dim={archived}
            data-live-clock
            >{phoneStarted(seconds)}</span
          >
        {:else}
          <span data-live-clock data-basis={row.closed_basis ?? undefined} class:oc-dim={archived}>{closedFor(row)}</span>
        {/if}
      {:else if column.key === 'status' && openFor(row)}
        
        {@const open = openFor(row)}
        <span class="oc-open-status" data-phase={open?.phase} role="status"
          >{openWords(open)}</span
        >
      {:else if column.key === 'status'}
        {@const hue = statusHue(row.lifecycle, null, null)}
        {@const plain = statusLabel(row.lifecycle, null, null)}
        {@const text = archived ? t('opscenter.closed.archived', { status: plain }) : plain}
        {#if phone}
          
          <span
            class="oc-status oc-status-mark"
            class:oc-dim={archived}
            role="img"
            aria-label={text}
            title={text}
            style={archived ? '' : `color:${hueDotToken(hue)}`}
          >
            <Icon name={lifecycleIcon(row.lifecycle, archived)} size={15} />
          </span>
        {:else}
        <span class="oc-status" style={`color:${hueDotToken(hue)}`}>
          <Icon name="check-circle" size={14} />
          {#if showStatusLabel}
            <span class="oc-status-label" class:oc-dim={archived} style={archived ? '' : `color:${hueLabelToken(hue)}`}>{text}</span>
          {:else}
            <span class="oc-visually-hidden">{text}</span>
          {/if}
        </span>
        {/if}
      {/if}
    {/snippet}
  </DataTable>
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }


    .oc-task-name {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
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

    .oc-status {
      display: inline-flex;
      align-items: center;
      gap: calc(var(--oc-space-1-5) + var(--oc-border));
      min-width: 0;
    }

    .oc-task-strong {
      font-weight: 600;
      color: var(--oc-text-primary);
    }

    .oc-started-compact {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .oc-status-mark {
      gap: 0;
    }

    .oc-status-label {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .oc-dim {
      color: var(--oc-text-dim);
    }

    .oc-open-status {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-cyan);
    }

    .oc-open-status[data-phase='opened'] {
      color: var(--oc-green);
    }

    .oc-open-status[data-phase='failed'] {
      color: var(--oc-coral);
    }
  }
</style>
