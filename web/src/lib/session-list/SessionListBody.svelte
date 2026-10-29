<script lang="ts">
  import SidebarList from '../sidebar-shell/SidebarList.svelte';
  import type { ShellView } from '../sidebar-shell/shell.svelte';
  import WidgetShell from '../../opscenter/widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../opscenter/widgets/shell/define-widget.svelte';
  import { SESSION_LIST_WIDGET_DEF } from './definition';
  import { VIEW_CHOICES } from './view-choices';
  import { watchViewState } from './view-state.svelte';

  let { view }: { view: ShellView } = $props();

  $effect(() => watchViewState());

  const widget = useWidget(SESSION_LIST_WIDGET_DEF, () => ({}), () =>
    Object.fromEntries(VIEW_CHOICES.map((choice) => [choice.id, { run: choice.run, on: choice.on() }])),
  );
</script>

<WidgetShell {widget} bare>
  <SidebarList {view} />
</WidgetShell>
