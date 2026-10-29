<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  import { MK2_ACTIONS, MK2_STATE } from '../task-manager-mk2/mk2-menu.svelte';

  export const TASK_MANAGER_MK2_ALL_WIDGET = defineWidget({ id: 'core.task-manager-mk2-all', scope: 'global', actions: MK2_ACTIONS, state: MK2_STATE });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import HuddleBody from '../../../cplugs/huddle/HuddleBody.svelte';
  import { AGGREGATE } from '../../../cplugs/huddle/huddle-model';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget, type WidgetHandle } from '../../widgets/shell/define-widget.svelte';
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import Mk2Bar from '../task-manager-mk2/Mk2Bar.svelte';
  import Mk2Count from '../task-manager-mk2/Mk2Count.svelte';
  import Mk2Frame from '../task-manager-mk2/Mk2Frame.svelte';
  import { mk2Bindings } from '../task-manager-mk2/mk2-menu.svelte';
  import { useMk2View } from '../task-manager-mk2/mk2-view-state.svelte';

  let props: CellProps = $props();

  const widget: WidgetHandle<typeof TASK_MANAGER_MK2_ALL_WIDGET> = useWidget(TASK_MANAGER_MK2_ALL_WIDGET, () => props, () => mk2Bindings(widget.state, AGGREGATE));
  useMk2View(widget.state);
</script>

{#snippet bar(items: HuddleItem[])}<Mk2Bar {items} />{/snippet}

<WidgetShell {widget} status="ready">
  <div class="oc-hdl-all" data-task-manager-all-cell>
    <Mk2Frame projectColors={widget.state['project-colors']} statusBar={widget.state['status-bar']} taskState={widget.state['task-state']} view={widget.state}><HuddleBody list={AGGREGATE} {bar} /></Mk2Frame>
    <Mk2Count list={null} />
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-hdl-all { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  }
</style>
