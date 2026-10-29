<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const AUTOMATIONS_ALL_WIDGET = defineWidget({ id: 'core.automations-all', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { automationsList, releaseAutomationsList, type AutomationsAnswer } from '../../api/automations-widget.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import AutomationRows from '../automations/AutomationRows.svelte';
  import { notTiedToSession } from '../automations/filter';
  import type { CellProps } from '../../lib/cell';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';

  let props: CellProps = $props();
  const widget = useWidget(AUTOMATIONS_ALL_WIDGET, () => props);

  let res = $state<Resource<AutomationsAnswer> | null>(null);

  $effect(() => {
    res = automationsList();
    return () => releaseAutomationsList();
  });

  const rows = $derived(res?.data ? notTiedToSession(res.data.automations) : []);
  const view = $derived<'loading' | 'unknown' | 'empty' | 'list'>(
    !res?.data ? (res && res.status !== 'loading' ? 'unknown' : 'loading') : rows.length > 0 ? 'list' : 'empty',
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = { loading: 'loading', unknown: 'error', empty: 'empty', list: 'ready' };
  const note = $derived(view === 'list' ? '' : t(`opscenter.cell.automations${view === 'empty' ? '_all' : ''}.${view}`));
</script>

<WidgetShell {widget} status={STATUS[view]} {note}>
  <ShellScroll>
    <div class="oc-aut oc-aut-all" data-automations-all-cell data-view={view}>
      {#if view === 'list'}<AutomationRows automations={rows} />{/if}
    </div>
  </ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-aut-all { padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); }
  }
</style>
