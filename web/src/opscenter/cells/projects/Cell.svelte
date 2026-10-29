<script lang="ts" module>
  import { countForProject } from './count';
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const PROJECTS_WIDGET = defineWidget({ id: 'core.projects', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { relative, leftTruncate, parseServerTime } from '../../lib/format';
  import { clock } from '../../lib/frozen-clock.svelte';
  import DataTable from '../../ui/DataTable.svelte';
  import Icon from '../../ui/Icon.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import { newSession, projects, sessions, type ProjectResponse } from '../../api';
  import { columns, COLUMNS_AT, phoneColumns } from './meta';
  import { projectsSortPref, sortRows, SORT_KEYS } from './sort.svelte';
  import SortControl from '../../ui/SortControl.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import { sortActions } from '../../widgets/menu/header-actions';
  import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';

  type Row = ProjectResponse & { sessionCount: number | null } & Record<string, unknown>;

  let props: CellProps = $props();
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(PROJECTS_WIDGET, () => props);
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
  const rowHeight = $derived(showDetail ? 40 : 24);

  function tildify(path: string): string {
    return path.replace(/^\/(?:Users|home)\/[^/]+/, '~');
  }

  const notice = $derived.by((): string => {
    if (projects.status === 'signed-out') return t('opscenter.projects.signed_out');
    if (projects.status === 'unavailable') return t('opscenter.projects.unavailable');
    if (projects.status === 'error') return projects.error ?? t('opscenter.projects.error');
    return '';
  });

  function minutesAgo(iso: string, now = Date.now()): number | null {
    const then = parseServerTime(iso);
    if (!Number.isFinite(then)) return null;
    return Math.max(0, Math.round((now - then) / 60000));
  }

  function updatedLabel(row: Row): string {
    if (!row.work_at) return t('opscenter.value.not_measured');
    const minutes = minutesAgo(row.work_at);
    return minutes === null ? t('opscenter.value.not_measured') : relative(minutes);
  }

  function rootLabel(row: Row): string {
    const source = row.root ?? row.path;
    const trimmed = source.replace(/\/+$/, '');
    const parts = trimmed.split('/');
    return parts[parts.length - 1] || source;
  }

  function sessionCountFor(project: ProjectResponse): number | null {
    if (sessions.status !== 'ok' || !sessions.data) return null;
    return countForProject(sessions.data, project);
  }

  function sessionsLabel(count: number | null): string {
    if (count === null) return t('opscenter.value.not_measured');
    return t('opscenter.projects.sessions', { count });
  }

  const rows = $derived.by((): Row[] => {
    if (projects.status !== 'ok' || !projects.data) return [];
    return projects.data.map((project) => ({
      ...project,
      sessionCount: sessionCountFor(project),
    }));
  });

  const frozenAt = clock.frozen ? Date.now() : null;
  const nowMs = $derived.by(() => {
    void clock.now;
    return frozenAt ?? Date.now();
  });

  const orderedRows = $derived(sortRows(rows, projectsSortPref.value, nowMs));

  const sortLabel = $derived(t(`opscenter.projects.sort.${projectsSortPref.value}`));
  const sortMenu = $derived<MenuNode[]>(
    SORT_KEYS.map((key) => ({
      id: key,
      label: t(`opscenter.projects.sort.${key}`),
      run: () => projectsSortPref.set(key),
    })),
  );

  const frameHeader = $derived(widget.frame);
  $effect(() => (frameHeader ? declareWidgetActions(frameHeader.hostId, 'sort', sortActions(sortMenu)) : undefined));

  function detailFor(row: Row): string {
    const shown = new Set(shownColumns.map((column) => column.key));
    const parts: string[] = [];
    if (!shown.has('sessions')) parts.push(sessionsLabel(row.sessionCount));
    if (!shown.has('path')) parts.push(leftTruncate(row.path, 28));
    return parts.join(t('opscenter.list.separator'));
  }
</script>

{#snippet sortControl()}
  <SortControl
    buttonText={t('opscenter.projects.sort.button', { label: sortLabel })}
    menuLabel={t('opscenter.projects.sort.menu')}
    menu={sortMenu}
  />
{/snippet}

<WidgetShell {widget} controls={sortControl}>
<ShellScroll>
{#if showBody}
  <DataTable
    columns={shownColumns}
    rows={limit === null ? orderedRows : orderedRows.slice(0, limit)}
    {rowHeight}
    headHeight={26}
    showHead={showHead}
    compact={phone}
    rowKey={(row) => row.root ?? row.path}
    onActivate={(row) => newSession(row)}
    rowLabel={(row) => t('opscenter.projects.new_session_row', { name: row.name })}
  >
    {#snippet cell(row: Row, column, _index)}
      {#if column.key === 'name'}
        <span class="oc-project-cell">
          <span class="oc-project-name">
            <span class="oc-row-icon">
              <Icon name="folder" size={14} />
            </span>
            <span>{row.name}</span>
          </span>
          {#if showDetail && detailFor(row)}
            <span class="oc-detail">{detailFor(row)}</span>
          {/if}
        </span>
      {:else if column.key === 'type'}
        <span class="oc-muted">{rootLabel(row)}</span>
      {:else if column.key === 'updated'}
        <span class="oc-muted">{updatedLabel(row)}</span>
      {:else if column.key === 'sessions'}
        <span class="oc-muted">{sessionsLabel(row.sessionCount)}</span>
      {:else if column.key === 'path'}
        <span class="oc-muted">{leftTruncate(row.path, 24)}</span>
      {:else if column.key === 'phoneSessions'}
        {#if row.sessionCount !== null && row.sessionCount > 0}
          <span class="oc-phone-badge">{row.sessionCount}</span>
        {/if}
      {:else if column.key === 'phonePath'}
        <span class="oc-phone-path">{leftTruncate(tildify(row.path), 34)}</span>
      {/if}
    {/snippet}
  </DataTable>
  {#if showHead && notice}
    <State inline kind={stateKindOf(projects.status)} title={notice} />
  {/if}
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-project-cell {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--oc-space-0-5);
      min-width: 0;
      overflow: hidden;
    }

    .oc-project-name {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      overflow: hidden;
    }

    .oc-project-name span:last-child {
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
      color: var(--oc-orange);
    }

    .oc-detail {
      display: block;
      margin-top: var(--oc-space-0-5);
      padding-left: calc(var(--oc-space-5) - var(--oc-space-0-5));
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-muted {
      color: var(--oc-text-secondary);
    }

    .oc-phone-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 18px;
      height: 16px;
      padding: 0 calc(var(--oc-space-1) + var(--oc-border));
      border-radius: 999px;
      background: var(--oc-orange);
      color: var(--oc-ground-chrome);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
    }

    .oc-phone-path {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-dim);
    }

  }
</style>
