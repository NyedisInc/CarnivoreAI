<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const KEEP_AWAKE_WIDGET = defineWidget({ id: 'core.keep-awake', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import DataTable from '../../ui/DataTable.svelte';
  import SessionFace from '../../../lib/sessions/SessionFace.svelte';
  import KeepAwakeIcon from '../../../lib/auto-sleep/KeepAwakeIcon.svelte';
  import { autoSleep } from '../../../lib/auto-sleep/auto-sleep-store.svelte';
  import { sessions, projects, type SessionInfo } from '../../api';
  import type { ColumnSpec } from '../../engine/types';
  import { projectOfRow } from '../running-sessions/project';
  import { derivedDisplayName } from '../../../lib/sessions/session-label';
  import { keptView, type KeptRow } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  type Row = KeptRow & Record<string, unknown>;

  let props: CellProps = $props();
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(KEEP_AWAKE_WIDGET, () => props);
  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const showProject = $derived(phone || atLeast(props.meta.widthStates, widthState, 'project'));
  const showBody = $derived(phone || heightState !== 'title');

  const columns = $derived.by((): ColumnSpec[] => {
    const list: ColumnSpec[] = [
      { key: 'status', headKey: '', minPx: 26, weight: 0, insetPx: 12 },
      { key: 'name', headKey: 'opscenter.column.name', minPx: 110, weight: 1.4 },
    ];
    if (showProject) list.push({ key: 'project', headKey: 'opscenter.column.project', minPx: 110, weight: 1 });
    list.push({ key: 'toggle', headKey: '', minPx: 40, weight: 0, align: 'end', insetPx: 8 });
    return list;
  });

  const view = $derived(
    autoSleep.status === 'ok' && autoSleep.data
      ? keptView(autoSleep.data, (sessions.data ?? []) as SessionInfo[])
      : null,
  );

  const notice = $derived.by((): string => {
    if (autoSleep.status === 'loading') return t('opscenter.keep_awake.loading');
    if (autoSleep.status === 'signed-out') return t('opscenter.keep_awake.signed_out');
    if (autoSleep.status === 'unavailable') return t('opscenter.keep_awake.unavailable');
    if (autoSleep.status === 'error' || !view) return autoSleep.error ?? t('opscenter.keep_awake.error');
    if (view.total === 0) return t('opscenter.keep_awake.empty');
    return '';
  });

  const mac = $derived.by((): { text: string; tone: 'held' | 'missing' | 'free' } | null => {
    if (!view) return null;
    if (view.macAwake) return { text: t('opscenter.keep_awake.mac_held'), tone: 'held' };
    if (view.total > 0) return { text: t('opscenter.keep_awake.mac_not_held'), tone: 'missing' };
    return { text: t('opscenter.keep_awake.mac_free'), tone: 'free' };
  });

  const rows = $derived((view?.rows ?? []) as Row[]);

  function labelFor(row: KeptRow): string {
    return row.info?.label ?? derivedDisplayName(row.name);
  }

  function projectOf(row: KeptRow): string {
    if (!row.info) return t('opscenter.value.not_measured');
    return projectOfRow(row.info, projects.data ?? []);
  }
</script>

{#snippet rowCell(row: Row, column: ColumnSpec, _index: number)}
  {#if column.key === 'status'}
    <span class="oc-ka-led">
      <SessionFace row={row.info ?? {}} size="9px" />
    </span>
  {:else if column.key === 'name'}
    <span class="oc-ka-name" data-keep-awake-row={row.name}>{labelFor(row)}</span>
  {:else if column.key === 'project'}
    <span class="oc-ka-project" class:oc-ka-muted={!row.info}>{projectOf(row)}</span>
  {:else if column.key === 'toggle'}
    <KeepAwakeIcon sessionName={row.name} />
  {/if}
{/snippet}

<WidgetShell {widget}>
<ShellScroll>
{#if showBody}
  {#if mac}
    <p class="oc-ka-mac" data-mac-awake={mac.tone} role="status">
      <span class="oc-ka-mac-mark" aria-hidden="true"></span>{mac.text}
    </p>
  {/if}
  {#if notice}
    <State inline kind={stateKindOf(autoSleep.status)} data-keep-awake-notice title={notice} />
  {:else}
    <DataTable
      columns={columns}
      rows={limit === null ? rows : rows.slice(0, limit)}
      rowHeight={28}
      headHeight={27}
      showHead={!phone}
      compact={phone}
      rowKey={(row) => row.name}
      cell={rowCell}
    />
    {#if view && view.unnamed > 0}
      <State inline title={t('opscenter.keep_awake.unnamed', { count: view.unnamed })} />
    {/if}
  {/if}
{/if}
</ShellScroll>
</WidgetShell>

<style>
  @layer components {

    .oc-ka-mac {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      margin: 0;
      padding: var(--oc-space-1-5) var(--oc-space-3);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
      color: var(--oc-text-dim);
    }

    .oc-ka-mac-mark {
      flex: 0 0 auto;
      width: 6px;
      height: 6px;
      border-radius: 1px;
      background: var(--oc-text-dim);
    }

    .oc-ka-mac[data-mac-awake='held'] {
      color: var(--oc-violet);
    }

    .oc-ka-mac[data-mac-awake='held'] .oc-ka-mac-mark {
      background: var(--oc-violet);
    }

    .oc-ka-mac[data-mac-awake='missing'] {
      color: var(--oc-yellow);
    }

    .oc-ka-mac[data-mac-awake='missing'] .oc-ka-mac-mark {
      background: var(--oc-yellow);
    }

    .oc-ka-led {
      display: inline-flex;
      align-items: center;
    }

    .oc-ka-name,
    .oc-ka-project {
      display: block;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .oc-ka-name {
      color: var(--oc-text-bright);
    }

    .oc-ka-project {
      color: var(--oc-text-secondary);
    }

    .oc-ka-muted {
      color: var(--oc-text-dim);
    }
  }
</style>
