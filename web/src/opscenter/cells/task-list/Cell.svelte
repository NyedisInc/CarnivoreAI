<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TASK_LIST_WIDGET = defineWidget({ id: 'core.task-list', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { t } from '../../../lib/i18n/index.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions, type DeclaredAction } from '../../widgets/menu/declared-actions.svelte';
  import ListBody from './ListBody.svelte';
  import { DENSITY_OPTION, GROUP_OPTION, densityOf, groupOf, type ListDensity, type ListGroupBy } from './model';
  import { holdList, listRowsFor } from './state.svelte';

  let props: CellProps = $props();
  const limit = $derived(props.limit ?? null);
  const options = $derived(props.options);
  const onOption = $derived(props.onOption);

  const widget = useWidget(TASK_LIST_WIDGET, () => props);

  const DENSITIES: readonly { id: ListDensity; key: string }[] = [
    { id: 'compact', key: 'opscenter.cell.task_list.density.menu_compact' },
    { id: 'full', key: 'opscenter.cell.task_list.density.menu_full' },
  ];

  const GROUPINGS: readonly { id: ListGroupBy; key: string }[] = [
    { id: 'status', key: 'opscenter.cell.task_list.group.status' },
    { id: 'project', key: 'opscenter.cell.task_list.group.project' },
  ];

  $effect(() => holdList());

  const density = $derived(densityOf(options));
  const rows = $derived(listRowsFor(options));
  const grouping = $derived(groupOf(options));

  const frameHeader = $derived(widget.frame);

  function setDensity(next: ListDensity): void {
    onOption?.(DENSITY_OPTION, next);
  }

  function setGrouping(next: ListGroupBy): void {
    onOption?.(GROUP_OPTION, next);
  }

  const choices = $derived<DeclaredAction[]>([
    ...GROUPINGS.map((one) => ({ id: `group:${one.id}`, label: t(one.key), checked: grouping === one.id, run: () => setGrouping(one.id) })),
    ...DENSITIES.map((one) => ({ id: `density:${one.id}`, label: t(one.key), checked: density === one.id, run: () => setDensity(one.id) })),
  ]);

  $effect(() => {
    if (!frameHeader || !onOption) return;
    return declareWidgetActions(frameHeader.hostId, 'list', choices);
  });
</script>

<WidgetShell {widget}>
  <ShellScroll>
    <ListBody {rows} {limit} {density} {grouping} />
  </ShellScroll>
</WidgetShell>
