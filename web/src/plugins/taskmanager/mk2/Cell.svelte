<script lang="ts" module>
  import { defineWidget } from '../../sdk/widgets';

  import { MK2_ACTIONS, MK2_STATE } from './mk2-menu.svelte';

  export const TASK_MANAGER_MK2_WIDGET = defineWidget({ id: 'core.task-manager-mk2', scope: 'session', actions: MK2_ACTIONS, state: MK2_STATE });
</script>

<script lang="ts">
  /* the widget menu */
  import type { CellProps } from '../../sdk/widgets';
  import HuddleBody from '../HuddleBody.svelte';
  import { sessionScopeFor } from '../../sdk/widgets';
  import { sessionsResource as sessions } from '../../sdk/widgets';
  import { activeTerminalSessionId } from '../../sdk/widgets';
  import { WidgetShell } from '../../sdk/widgets';
  import { useWidget, type WidgetHandle } from '../../sdk/widgets';
  import { t } from '../../sdk';
  import type { HuddleItem } from '../huddle-model';
  import Mk2Bar from './Mk2Bar.svelte';
  import Mk2Count from './Mk2Count.svelte';
  import Mk2Frame from './Mk2Frame.svelte';
  import { mk2Bindings } from './mk2-menu.svelte';
  import { hideableStatuses } from './mk2-statuses';
  import { useMk2View } from './mk2-view-state.svelte';

  let props: CellProps = $props();

  const resolved = $derived(props.scope ?? sessionScopeFor(sessions.data, activeTerminalSessionId()));
  const list = $derived(resolved?.projectId == null ? null : String(resolved.projectId));
  const widget: WidgetHandle<typeof TASK_MANAGER_MK2_WIDGET> = useWidget(TASK_MANAGER_MK2_WIDGET, () => props, () => mk2Bindings(widget.state, list ?? ''));
  useMk2View(widget.state);
</script>

{#snippet bar(items: HuddleItem[])}<Mk2Bar {items} />{/snippet}

<WidgetShell {widget} status={list === null ? 'none' : 'ready'} note={t(resolved ? 'opscenter.cell.task_manager_mk2.no_project' : 'opscenter.cell.task_manager_mk2.no_session')}>
  <div class="oc-hdl" data-task-manager-cell={list ?? ''}>
    {#if list !== null}{#key list}<Mk2Frame projectColors={widget.state['project-colors']} statusBar={widget.state['status-bar']} hiddenStatuses={hideableStatuses(widget.state['hidden-statuses'])} onShowAll={() => { widget.state['hidden-statuses'] = []; }} taskState={widget.state['task-state']} view={widget.state}><HuddleBody {list} {bar} /></Mk2Frame>{/key}<Mk2Count {list} />{/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-hdl { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  }
</style>
