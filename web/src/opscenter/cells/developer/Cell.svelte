<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { MONITORS } from './meta';

  const MONITOR_IDS: readonly string[] = MONITORS.map((m) => m.id);

  export const DEVELOPER_WIDGET = defineWidget({
    id: 'core.developer',
    scope: 'global',
    actions: [],
    state: { tab: { home: 'device', default: MONITOR_IDS[0] as string, valid: (value: unknown): value is string => typeof value === 'string' && MONITOR_IDS.includes(value), legacyKey: 'carnivore.tabs.developer-widget' } },
  });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import Tabs, { panelAttrs, type TabDef } from '../../ui/Tabs.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  const props: CellProps = $props();

  const ID_BASE = 'oc-dv';

  const widget = useWidget(DEVELOPER_WIDGET, () => props);
  const active = $derived(widget.state.tab);

  const tabs = $derived<TabDef[]>(MONITORS.map((m) => ({ id: m.id, label: t(m.labelKey) })));
  const monitor = $derived(MONITORS.find((m) => m.id === active) ?? MONITORS[0]);

  function select(id: string): void {
    widget.state.tab = id;
  }
</script>

<WidgetShell {widget}>
<div class="oc-dv" data-developer-cell>
  <Tabs {tabs} {active} onSelect={select} label={t('opscenter.cell.developer.tabs')} idBase={ID_BASE} />
  {#if monitor}
    {@const Body = monitor.component}
    <div class="oc-dv-panel" data-developer-panel={monitor.id} {...panelAttrs(ID_BASE, monitor.id)}>
      <Body {...props} />
    </div>
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-dv { display: flex; flex-direction: column; height: 100%; min-height: 0; }

    .oc-dv-panel { flex: 1 1 0; min-height: 0; overflow: hidden; }

    .oc-dv :global(.oc-ptab) { flex: 1 1 0; justify-content: center; padding-inline: var(--oc-space-1); }

    .oc-dv :global(.oc-ptab__label) { overflow: hidden; text-overflow: ellipsis; }
  }
</style>
