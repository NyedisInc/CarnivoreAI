<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const AUTOMATIONS_WIDGET = defineWidget({ id: 'core.automations', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { automationsList, releaseAutomationsList, sessionUuidOfRow, type AutomationsAnswer } from '../../api/automations-widget.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import AutomationRows from './AutomationRows.svelte';
  import { forSession } from './filter';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';

  let props: CellProps = $props();

  const widget = useWidget(AUTOMATIONS_WIDGET, () => props);
  const sessionId = $derived(widget.sessionId);
  const rowId = $derived.by(() => {
    const info = (sessions.data ?? []).find((s) => s.session.id === sessionId);
    return typeof info?.session_row_id === 'number' ? info.session_row_id : null;
  });

  let res = $state<Resource<AutomationsAnswer> | null>(null);
  let uuid = $state<string | null | undefined | 'unknown'>(undefined);

  $effect(() => {
    res = automationsList();
    return () => releaseAutomationsList();
  });

  $effect(() => {
    const id = rowId;
    uuid = undefined;
    if (id === null) return;
    let live = true;
    sessionUuidOfRow(id).then(
      (found) => { if (live) uuid = found; },
      () => { if (live) uuid = 'unknown'; },
    );
    return () => { live = false; };
  });

  const rows = $derived(res?.data && uuid && uuid !== 'unknown' ? forSession(res.data.automations, uuid) : []);
  const view = $derived<'none' | 'loading' | 'unknown' | 'empty' | 'list'>(
    !sessionId || rowId === null ? 'none'
      : uuid === 'unknown' || (!res?.data && res && res.status !== 'loading') ? 'unknown'
      : !res?.data || uuid === undefined ? 'loading'
      : rows.length > 0 ? 'list'
      : 'empty',
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = { none: 'none', loading: 'loading', unknown: 'error', empty: 'empty', list: 'ready' };
  const note = $derived(view === 'list' ? '' : t(`opscenter.cell.automations.${view === 'none' ? 'no_session' : view}`));
</script>

<WidgetShell {widget} status={STATUS[view]} {note}>
  <ShellScroll>
    <div class="oc-aut" data-automations-cell data-view={view} data-session={sessionId || undefined}>
      {#if view === 'list'}<AutomationRows automations={rows} />{/if}
    </div>
  </ShellScroll>
</WidgetShell>

<style>
  @layer components {
    .oc-aut { padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); }
  }
</style>
