<script lang="ts">
  import { motionReduced } from '../motion/motion';
  import { fly } from 'svelte/transition';
  import { t } from '../i18n/index.svelte';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import type { ZoneItem } from '../drawer-zone/zone-model';
  import { placementHead } from '../../opscenter/widgets/placement-options';
  import { RAIL_RATIO_DEFAULT, RAIL_RATIO_MAX, RAIL_RATIO_MIN, RAIL_RATIO_STEP, RAIL_SPECS, type RailEdge } from './rail-model';
  import { railStores } from './rail-store.svelte';
  import { sectionStyle } from './rail-sections';
  import { railOutSizes } from './rail-out-size.svelte';
  import { railSlideout } from './slideout.svelte';
  import { panelPins } from '../widget-bars/panel-pins.svelte';
  import { barPinned } from '../widget-bars/bar-pin-action';
  import { untrack } from 'svelte';
  import { provideOpenFocus } from '../../opscenter/shell/open-focus.svelte';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';
  import { activeAgent, pinnedAgent } from '../widget-bars/pinned-scope';
  import RailResizeHandle from './RailResizeHandle.svelte';
  import PlacementBody from '../zone-shell/PlacementBody.svelte';
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import type { Zone } from '../zone-shell/zone.svelte';
  import type { TabRef } from '../zone-shell/zone-types';
  import SplitDivider from '../split-divider/SplitDivider.svelte';

  interface ShownEntry {
    item: ZoneItem;
    manifest: WidgetManifest;
    key: string;
    section: number;
  }

  let {
    entries,
    zones,
    sections = 1,
    ratio = RAIL_RATIO_DEFAULT,
    edge = 'side',
    instant = false,
    onratio,
    onratiosave,
    onclose,
  }: {
    entries: ShownEntry[];
    zones: readonly Zone[];
    sections?: number;
    ratio?: number;
    edge?: RailEdge;
    instant?: boolean;
    onratio: (ratio: number) => void;
    onratiosave: () => void;
    onclose: () => void;
  } = $props();

  const side = $derived(edge === 'side');
  const axis = $derived(RAIL_SPECS[edge].axis);
  const split = $derived(sections > 1 && entries.length > 1);
  let winW = $state(typeof window === 'undefined' ? 1280 : window.innerWidth);
  let winH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
  const extent = $derived(railOutSizes.shown(edge, side ? winW : winH));

  const reduced = motionReduced();

  let panel = $state<HTMLElement | null>(null);
  const openFocus = provideOpenFocus();
  $effect(() => {
    if (panel && railSlideout.takePressFocus(edge)) {
      panel.focus({ preventScroll: true });
      openFocus.pending = true;
    }
  });

  function nameOf(entry: ShownEntry): string {
    return placementHead(entry.manifest.id, entry.item.options)?.title ?? t(entry.manifest.titleKey);
  }

  const drawn = new Map<string, ShownEntry>();

  function entryOf(key: string): ShownEntry | undefined {
    const live = entries.find((one) => one.key === key);
    if (live) drawn.set(key, live);
    return live ?? drawn.get(key);
  }

  const pinOf = (section: number) => pins.find((one) => one.entry.section === section);

  const widgetNames = $derived(entries.map((entry) => nameOf(entry)).join(', '));
  const pins = $derived(entries.map((entry) => {
    const row = panelPins.pinnedRow(edge, entry.key);
    return { entry, row, agent: row === null ? null : pinnedAgent(row) };
  }));
  const firstPinned = $derived(pins.find((one) => one.row !== null) ?? null);
  const edgeLabel = $derived(firstPinned ? t('widget_bars.edge_pinned', { agent: firstPinned.agent?.name ?? '' }) : t('widget_bars.edge'));
  const parts = $derived(pins.map((one) => ({ section: one.entry.section, pinned: one.row !== null })));

  function togglePin(section: number): void {
    const entry = entries.find((one) => one.section === section);
    if (!entry) return;
    if (panelPins.pinned(edge, entry.key)) {
      panelPins.unpin(edge, entry.key);
      terminalLayout.announce(t('widget_bars.announce.unpinned', { widget: nameOf(entry) }));
      return;
    }
    const active = activeAgent();
    if (active.row === null) return;
    panelPins.pin(edge, entry.key, active.row);
    terminalLayout.announce(t('widget_bars.announce.pinned', { widget: nameOf(entry), agent: active.name }));
  }

  const PIN_GONE_SETTLE_MS = 2000;
  const pinGone = $derived(pins.some((one) => one.agent?.state === 'gone'));
  $effect(() => {
    if (!pinGone) return;
    const timer = setTimeout(() => {
      untrack(() => {
        terminalLayout.announce(t('widget_bars.pin_gone', { widget: widgetNames }));
        railSlideout.close(edge);
      });
    }, PIN_GONE_SETTLE_MS);
    return () => clearTimeout(timer);
  });
  function onkeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    if (barPinned(edge)) return;
    if (event.target instanceof Element && event.target.closest('.xterm')) return;
    event.stopPropagation();
    onclose();
  }
</script>

{#snippet body(tab: TabRef)}
  {@const entry = entryOf(tab.key)}
  {#if entry}
    <PlacementBody host="rail" source={railStores[edge]} manifest={entry.manifest} target={entry.item.target ?? null} view={entry.item.view ?? null} instance={entry.item.instance ?? null} pinRowId={pinOf(entry.section)?.row ?? null} options={entry.item.options} {edge} placementKey={entry.key} />
  {/if}
{/snippet}

<svelte:window bind:innerWidth={winW} bind:innerHeight={winH} />
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section
  class="rail-out"
  class:rail-out--side={side}
  class:rail-out--bottom={!side}
  style={side ? `width: ${extent}px` : `height: ${extent}px`}
  data-rail-edge={edge}
  data-rail-extent={extent}
  data-rail-sections-open={entries.length}
  bind:this={panel}
  tabindex="-1"
  role="region"
  aria-label={widgetNames}
  data-rail-slideout={entries[0]?.manifest.id}
  {onkeydown}
  transition:fly={{ x: side ? 24 : 0, y: side ? 0 : 24, duration: reduced || instant ? 0 : 140 }}
>
  {#each entries as entry (entry.section)}
    <div class="rail-out__section" data-rail-out-section={entry.section} data-rail-out-widget={entry.manifest.id}
      role="group" aria-label={nameOf(entry)}
      style={sectionStyle(axis, entry.section, split ? 2 : 1, ratio)}>
      {#key `${entry.key}:${pinOf(entry.section)?.row ?? ''}`}
        <ZoneShell zone={zones[entry.section]!} mount="active" tab={body} />
      {/key}
    </div>
  {/each}
  {#if split}
    <SplitDivider {axis} {ratio} min={RAIL_RATIO_MIN} max={RAIL_RATIO_MAX} step={RAIL_RATIO_STEP} reset={RAIL_RATIO_DEFAULT}
      label={t(side ? 'session_rail.divider' : 'session_rail.divider_bottom')} onpreview={onratio} oncommit={onratiosave} />
  {/if}
  <RailResizeHandle {edge} label={edgeLabel} {parts} cut={split ? ratio : null} pinnable={activeAgent().row !== null} onpin={togglePin} />
</section>

<style>
  @layer components {
    .rail-out {
      position: absolute;
      z-index: 40;
      min-height: 0;
      background: var(--oc-ground-panel);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      outline: none;
    }

    .rail-out--side {
      top: 0;
      right: 100%;
      bottom: 0;
    }

    .rail-out--bottom {
      left: 0;
      right: 0;
      bottom: 100%;
      box-shadow: 1px 0 0 0 var(--oc-line-frame);
    }

    .rail-out__section {
      position: absolute;
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      container: oc-head / inline-size;
    }

    .rail-out--side .rail-out__section {
      margin-left: 2px;
    }

    .rail-out--bottom .rail-out__section {
      margin-top: 2px;
    }

  }
</style>
