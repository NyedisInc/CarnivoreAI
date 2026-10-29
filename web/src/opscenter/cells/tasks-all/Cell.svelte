<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TASKS_ALL_WIDGET = defineWidget({ id: 'core.tasks-all', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* all session tasks */
  import { allSessionTasks, releaseAllSessionTasks, type AllSessionTasks } from '../../api/session-tasks.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import TaskRows from '../tasks/TaskRows.svelte';
  import type { CellProps } from '../../lib/cell';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const widget = useWidget(TASKS_ALL_WIDGET, () => props);

  let res = $state<Resource<AllSessionTasks> | null>(null);

  $effect(() => {
    res = allSessionTasks();
    return () => releaseAllSessionTasks();
  });

  const data = $derived(res?.data ?? null);
  const view = $derived<'loading' | 'unknown' | 'empty' | 'list'>(
    !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading') : data.sessions.length > 0 ? 'list' : 'empty',
  );
</script>

<WidgetShell {widget} status={view === 'list' ? 'ready' : view === 'unknown' ? 'error' : view}
  note={t(view === 'empty' ? 'opscenter.cell.tasks_all.empty' : `opscenter.cell.tasks.${view}`)}>
<div class="oc-tsk oc-tsk-all" data-tasks-all-cell data-view={view}>
  {#if view === 'list' && data}
    {#each data.sessions as group (group.session_id)}
      <section class="oc-tsk-group" data-tasks-session={group.session_id}>
        <h4 class="oc-tsk-head">
          <bdi class="oc-tsk-name">{group.label ?? group.session_id}</bdi>
          <span class="oc-tsk-count">{t('opscenter.cell.tasks.progress', { done: group.counts.completed, total: group.tasks.length })}</span>
        </h4>
        <TaskRows tasks={group.tasks} />
      </section>
    {/each}
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-tsk-all { height: 100%; min-height: 0; overflow-y: auto; padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); }

    .oc-tsk-group + .oc-tsk-group { margin-top: var(--oc-space-2); }

    .oc-tsk-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-1); margin: 0; padding: calc(var(--oc-space-1) - var(--oc-border)) var(--oc-space-1-5); font-family: var(--font-mono); font-size: var(--oc-fs-label); font-weight: normal; letter-spacing: 0.08em; text-transform: uppercase; color: var(--oc-orange); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .oc-tsk-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .oc-tsk-count { flex: 0 0 auto; color: var(--oc-text-dim); letter-spacing: normal; text-transform: none; }
  }
</style>
