<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const ANALYTICS_WIDGET = defineWidget({ id: 'core.analytics', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { LayoutStore } from '../../engine/layout.svelte';
  import type { CellMeta } from '../../engine/types';
  import { pickTier } from '../../viz/density';
  import { VIZ_REGISTRY } from '../../viz/registry';
  import { vizFloor, vizOf } from '../../viz/specs';
  import { useFrameGuide } from '../../widgets/chrome/resize-guide.svelte';
  import { FIT_TOLERANCE_PX } from '../../widgets/fits';
  import ChartPending from './ChartPending.svelte';
  import { readChartTitle, rememberChartTitle } from './chart-titles';
  import AlarmStrip from '../../viz/AlarmStrip.svelte';
  import { alarmFor, seriesUnit } from '../../viz/tripwire-model';
  import { followTripwires } from '../../viz/tripwire-follow';
  import { tripwires } from '../../viz/tripwires.svelte';
  import { analytics } from './state.svelte';
  import { claimFrameTitle, useFrameHeader } from '../../shell/frame-header.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: { instance: string; width: number; height: number; store?: LayoutStore; meta?: CellMeta } = $props();
  const { instance, width, height } = $derived(props);
  const widget = useWidget(ANALYTICS_WIDGET, () => props);
  const config = $derived(analytics.charts[instance.slice('analytics:'.length)]);
  const Renderer = $derived(config ? VIZ_REGISTRY[vizOf(config)].component : null);
  let steps = $state<{ w?: string; h?: string }>({});
  const picked = $derived(pickTier(width, height, steps));
  const alarm = $derived(config ? alarmFor(tripwires.list, config.id) : { state: 'ok' as const, wire: null });
  const alarmUnit = $derived(config ? seriesUnit(Object.fromEntries(analytics.catalog.map((entry) => [entry.id, entry.unit ?? ''])), config.series.find((item) => item.visible !== false) ?? config.series[0]!) : '');
  const belowFloor = $derived.by((): boolean => {
    if (!config || width <= 0 || height <= 0) return false;
    const min = vizFloor(config);
    return width + FIT_TOLERANCE_PX < min.width || height + FIT_TOLERANCE_PX < min.height;
  });
  const frameGuide = useFrameGuide();
  $effect(() => {
    if (!frameGuide) return;
    frameGuide.bodyFloorPx = config ? vizFloor(config) : null;
    return () => { frameGuide.bodyFloorPx = null; };
  });
  $effect(() => { followTripwires(); });
  const frameHeader = useFrameHeader();
  const chartId = $derived(instance.slice('analytics:'.length));
  $effect(() => {
    if (!frameHeader || (config && vizOf(config) === 'timeline')) return;
    const mine = config ? config.title || null : readChartTitle(chartId);
    if (config) rememberChartTitle(chartId, mine);
    return claimFrameTitle(frameHeader, mine);
  });
  $effect(() => { if (picked.w !== steps.w || picked.h !== steps.h) steps = { w: picked.w, h: picked.h }; });
</script>

<WidgetShell {widget}>
{#if config && Renderer}
  <div class="alarm-frame" class:alarm-frame--firing={alarm.state === 'firing'} data-alarm-state={alarm.state}>
    <AlarmStrip {alarm} unit={alarmUnit} />
    <div class="alarm-frame__body" class:alarm-frame__body--clipped={belowFloor}><Renderer {config} {instance} tier={picked.tier} /></div>
  </div>
{:else}
  <ChartPending />
{/if}
</WidgetShell>

<style>
  @layer components {
    .alarm-frame { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); min-width: 0; height: 100%; box-sizing: border-box; border: 1px solid transparent; }

    .alarm-frame--firing { border-color: var(--oc-coral); }

    .alarm-frame__body { grid-row: 2; min-width: 0; min-height: 0; }

    .alarm-frame__body--clipped { overflow: hidden; }
  }
</style>
