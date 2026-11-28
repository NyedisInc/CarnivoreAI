<script lang="ts">
  import { auth } from '../../opscenter/api/auth.svelte';
  import { pluginsStore } from '../plugins/store.svelte';
  import SidebarList from '../sidebar-shell/SidebarList.svelte';
  import { repaintDrawer, type ShellView } from '../sidebar-shell/shell.svelte';
  import WidgetShell from '../../opscenter/widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../opscenter/widgets/shell/define-widget.svelte';
  import { SESSION_LIST_WIDGET_DEF } from './definition';
  import { VIEW_CHOICES } from './view-choices';
  import { watchViewState } from './view-state.svelte';

  let { view }: { view: ShellView } = $props();

  $effect(() => watchViewState());

  $effect(() => {
    if (auth.state === 'signed-out') return;
    const stopSlots = pluginsStore.acquire({ includeSlots: true });
    const stopRepaint = pluginsStore.onSlots(() => {
      repaintDrawer();
    });
    return () => {
      stopRepaint();
      stopSlots();
    };
  });

  const widget = useWidget(SESSION_LIST_WIDGET_DEF, () => ({}), () =>
    Object.fromEntries(VIEW_CHOICES.map((choice) => [choice.id, { run: choice.run, on: choice.on(), hidden: choice.available?.() === false }])),
  );
</script>

<WidgetShell {widget} bare>
  <SidebarList {view} />
</WidgetShell>
