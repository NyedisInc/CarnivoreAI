<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TASKS_WIDGET = defineWidget({ id: 'core.tasks', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  /* its own sentence */
  import type { CellProps } from '../../lib/cell';
  import { sessionTasks, releaseSessionTasks, type SessionTasks } from '../../api/session-tasks.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import TaskRows from './TaskRows.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';

  let props: CellProps = $props();

  const widget = useWidget(TASKS_WIDGET, () => props);
  const sessionId = $derived(widget.sessionId);

  let res = $state<Resource<SessionTasks> | null>(null);

  $effect(() => {
    const id = sessionId;
    if (!id) { res = null; return; }
    res = sessionTasks(id);
    return () => releaseSessionTasks(id);
  });

  const data = $derived(res?.data ?? null);
  const view = $derived<'none' | 'loading' | 'unknown' | 'empty' | 'list' | 'unsupported' | 'remote'>(
    !sessionId ? 'none'
      : !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading')
      : data.state === 'ok' ? 'list'
      : data.state,
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = {
    list: 'ready', none: 'none', loading: 'loading', unknown: 'error', empty: 'empty', unsupported: 'none', remote: 'none',
  };
</script>

<WidgetShell {widget} status={STATUS[view]} note={t(view === 'none' ? 'opscenter.cell.tasks.no_session' : `opscenter.cell.tasks.${view}`)}>
  <div class="oc-tsk" data-tasks-cell data-view={view} data-session={sessionId || undefined}>
    {#if data && view === 'list'}<TaskRows tasks={data.tasks} />{/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-tsk { height: 100%; min-height: 0; overflow-y: auto; padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); }
  }
</style>
