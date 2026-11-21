<script lang="ts">
  import { isGlobalWidget } from '../../opscenter/widgets/global-scope';
  import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
  import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { onRailContextMenu, onRailMenuKey } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';
  import { placementHead } from '../../opscenter/widgets/placement-options';
  import { t } from '../i18n/index.svelte';
  import { railIconHidden, setRailIconHidden, startRailIcons } from '../sidebar-widgets/rail-icons.svelte';
  import { zoneItemKey } from '../drawer-zone/zone-model';
  import { RAIL_MAX_SECTIONS, RAIL_SPECS, type RailEdge } from './rail-model';
  import { clearRailAims, clearRailDrops, liftRails, placeInRail, railAims, railCarry, railDrags, railStores } from './rail-store.svelte';
  import { canSplitAt } from './rail-sections';
  import { createRailMotion } from '../zone-motion/rail-motion';
  import { registerDropHost } from '../motion-grid';
  import { railSlideout } from './slideout.svelte';
  import { railOutSizes } from './rail-out-size.svelte';
  import { RAIL_PUSH_DEBOUNCE_MS } from './rail-size';
  import { widgetBars } from '../widget-bars/bar-settings.svelte';
  import { barLead } from '../widget-bars/bar-lead.svelte';
  import { BAR_SIZES, HANDLE_PX, barLabel, barVars } from '../widget-bars/bar-size';
  import { barOut, inFlow, showsHandle, showsPin } from '../widget-bars/bar-state';
  import { barPinIconId, stripPinsOffered } from '../widget-bars/bar-pin-action';
  import EditCell from '../zone-shell/EditCell.svelte';
  import { createBarVisibility } from '../widget-bars/bar-visibility.svelte';
  import ZoneHandle from '../zone-shell/ZoneHandle.svelte';
  import BarPin from '../widget-bars/BarPin.svelte';
  import BarEdge from '../widget-bars/BarEdge.svelte';
  import { BarDrag, dragLook } from '../widget-bars/bar-drag.svelte';
  import { panelPins } from '../widget-bars/panel-pins.svelte';
  import { pinnedAgent } from '../widget-bars/pinned-scope';
  import { pinLetter } from '../widget-bars/pin-letters';
  import { sideBudget } from './side-budget.svelte';
  import { untrack } from 'svelte';
  import RailSlideout from './RailSlideout.svelte';
  import ZoneKeys from '../zone-shell/ZoneKeys.svelte';
  import { createZone, type Zone } from '../zone-shell/zone.svelte';
  import type { KeyFace, TabRef } from '../zone-shell/zone-types';
  import { railBodyKey } from './rail-body-key';
  import RailKeyMenu from '../widget-menu/RailKeyMenu.svelte';
  import { hasOptions, railTip } from '../widget-menu/option-nodes';
  import './rail-layer.css';

  let { edge = 'side' }: { edge?: RailEdge } = $props();

  const spec = $derived(RAIL_SPECS[edge]);
  const store = $derived(railStores[edge]);
  const drag = $derived(railDrags[edge]);
  const aim = $derived(railAims[edge]);
  const horizontal = $derived(spec.axis === 'x');

  $effect(() => {
    store.start();
    widgetBars.start();
    startRailIcons();
  });

  const motion = createRailMotion({
    get edge() { return edge; },
    get axis() { return spec.axis; },
    sections: () => sections.map((section) => section.map((entry) => entry.key)),
    cuts: () => cuts,
    canSplit: (section, key) => canSplitAt(store.layout, section, key),
    place(key, spot, kind) {
      if (kind) {
        placeInRail(edge, kind, spot);
        return;
      }
      const item = store.items.find((one) => zoneItemKey(one) === key);
      if (item) placeInRail(edge, item.widget, spot, item.target, item);
    },
    leave(key, to) {
      const item = store.items.find((one) => zoneItemKey(one) === key);
      if (!item) return;
      if (to) placeInRail(to.edge as RailEdge, item.widget, to.spot, item.target, item);
      else if (store.remove(key)) {
        const entry = entryOf.get(key);
        terminalLayout.announce(t('session_rail.announce.removed', { title: entry ? entry.head?.title ?? t(entry.manifest.titleKey) : key }));
      }
    },
    onLift: (key) => liftRails(key),
    onAim(aim) {
      clearRailAims();
      if (!aim) return;
      if (aim.section !== null) {
        railAims[edge].section = aim.section;
        railAims[edge].split = aim.offer;
        railAims[edge].onBox = aim.onBox;
        drag.state.index = aim.index;
      }
      if (aim.across) {
        const { edge: to, spot, offer } = aim.across;
        railAims[to as RailEdge].split = offer;
        railAims[to as RailEdge].onBox = spot.split;
        if (!spot.split) {
          railAims[to as RailEdge].section = spot.section;
          railDrags[to as RailEdge].state.index = spot.index;
        }
      }
    },
    onEnd: clearRailDrops,
  });
  $effect(() => {
    const keys = strip?.querySelector<HTMLElement>('[data-rail-sections]');
    return keys ? motion.attach(keys) : undefined;
  });
  $effect(() => {
    void [sections, cuts, size, labelAt, editing];
    untrack(() => motion.sync());
  });

  $effect(() => {
    if (!strip) return;
    return registerDropHost(strip, {
      id: `zone:rail-${edge}`,
      accept: (kind, ev) => motion.accept(kind, ev),
      takes: (kind) => !!resolvePlacement({ widget: kind }),
      add: (kind) => placeInRail(edge, kind),
    });
  });

  const barDrag = new BarDrag(edge, () => widgetBars.view[edge], () => visibility.fold());
  const size = $derived(barDrag.preview && barDrag.preview !== 'closed' ? barDrag.preview : widgetBars.view[edge].size);
  const labelAt = $derived(BAR_SIZES[size][edge].label);

  const editing = $derived(layoutEditor.active);
  const bar = $derived(widgetBars.view[edge]);
  const allSections = $derived(
    store.sections.map((section) =>
      section.flatMap((item) => {
        const resolved = resolvePlacement({ widget: item.widget, view: item.view, target: item.target ?? null, instance: item.instance ?? null });
        return resolved
          ? [{ item, placement: resolved, manifest: resolved.manifest, key: zoneItemKey(item), cell: resolved.cell, iconWidget: resolved.iconWidget, head: placementHead(item.widget, item.options) }]
          : [];
      }),
    ),
  );
  const sections = $derived(allSections.map((section) => (editing ? section : section.filter((entry) => !railIconHidden(entry.key)))));
  const drawnCount = $derived(sections.reduce((sum, section) => sum + section.length, 0));
  const cuts = $derived(store.cuts);
  const shown = $derived(
    railSlideout.shown(edge).flatMap((key) => {
      const at = sections.findIndex((section) => section.some((entry) => entry.key === key));
      const entry = at >= 0 ? sections[at]!.find((one) => one.key === key) : undefined;
      return entry ? [{ ...entry, section: at }] : [];
    }),
  );
  const openKeys = $derived(new Set(shown.map((entry) => entry.key)));
  $effect.pre(() => {
    for (const entry of shown) untrack(() => panelPins.adoptLegacy(edge, entry.section, entry.key));
  });
  const lockedRow = (key: string): number | null => (editing ? null : panelPins.pinnedRow(edge, key));
  const letterOf = (key: string): string => {
    const row = lockedRow(key);
    return row === null ? '' : pinLetter(row);
  };
  const keyWords = (key: string, title: string): string => {
    const row = lockedRow(key);
    if (row === null) return title;
    const agent = pinnedAgent(row);
    return `${t('widget_bars.key_pinned', { widget: title, agent: agent.name })}${agent.suffix ? `, ${t(`widget_bars.state.${agent.suffix}`)}` : ''}`;
  };
  let strip = $state<HTMLElement | null>(null);
  const visibility = createBarVisibility(
    edge,
    () => ({ show: bar.show, mode: bar.mode, together: widgetBars.view.together, drawn: drawnCount > 0, editing, panelShown: shown.length > 0 }),
    () => strip,
  );
  const look = $derived(dragLook(visibility.state, barDrag.preview));
  const barPlace = $derived(bar.mode === 'pinned' ? ['compact', 'cozy', 'detailed'].indexOf(bar.size) + 1 : 0);
  const present = $derived(look !== 'absent');
  const drop = $derived(drag.state.index !== null || aim.split !== null ? 'aimed' : drag.state.carrying ? 'open' : undefined);
  const ghostAfter = $derived(drag.state.carrying ? aim.split : null);
  const carriedKey = $derived(drag.state.carrying ? railCarry.key : null);
  const pinId = $derived(barPinIconId(edge));
  const pinHidden = $derived(railIconHidden(pinId));
  const pinDrawn = $derived(showsPin(look) && stripPinsOffered() && (editing || !pinHidden));


  let winW = $state(typeof window === 'undefined' ? 1280 : window.innerWidth);
  let winH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
  const wantPush = $derived(look === 'held' ? railOutSizes.shown(edge, horizontal ? winH : winW) : 0);
  const wantFlow = $derived(inFlow(look));
  let pushPx = $state(0);
  let flowed = $state(untrack(() => wantFlow));
  $effect(() => {
    sideBudget.hold('slideout', horizontal ? 0 : wantPush);
    return () => sideBudget.hold('slideout', 0);
  });
  $effect(() => {
    const want = wantPush;
    const flow = wantFlow;
    if (want === 0 || untrack(() => pushPx) === 0) {
      pushPx = want;
      flowed = flow;
      return;
    }
    const timer = setTimeout(() => {
      pushPx = want;
      flowed = flow;
    }, RAIL_PUSH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  });

  function close(): void {
    const key = shown[0]?.key ?? null;
    railSlideout.close(edge);
    if (!key || !strip) return;
    for (const item of strip.querySelectorAll<HTMLElement>('[data-zone-item]')) if (item.dataset['zoneItem'] === key) item.focus();
  }

  function onedit(event: KeyboardEvent, key: string, title: string): void {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      if (store.remove(key)) terminalLayout.announce(t('session_rail.announce.removed', { title }));
    }
  }

  let keyMenu = $state<{ key: string; anchor: HTMLElement } | null>(null);

  function press(key: string): void {
    if (editing) return;
    const wasOut = railSlideout.shown(edge).length > 0;
    if (railSlideout.press(edge, key) && !wasOut) barLead.take(edge);
  }

  const entryOf = $derived(new Map(sections.flat().map((entry) => [entry.key, entry])));

  function face(tab: TabRef): KeyFace {
    const entry = entryOf.get(tab.key)!;
    const title = entry.head?.title ?? t(entry.manifest.titleKey);
    return {
      title,
      ariaLabel: editing ? t('session_rail.edit_key', { title }) : keyWords(entry.key, title),
      tip: editing
        ? [t('session_rail.edit_key', { title }), t('session_rail.tip.options')].join('\n')
        : lockedRow(entry.key) !== null ? keyWords(entry.key, title) : railTip(entry.manifest, entry.item.view, (key) => t(key), entry.head?.title),
      label: entry.head?.title ?? barLabel(entry.manifest),
      icon: entry.head?.icon ?? entry.manifest.icon,
      global: isGlobalWidget(entry.iconWidget),
      chip: editing && hasOptions(entry.manifest, entry.cell, editing),
      letter: letterOf(entry.key),
      tone: entry.manifest.iconTone,
    };
  }

  const zones: Zone[] = Array.from({ length: RAIL_MAX_SECTIONS }, (_, s) => createZone({
    key: `bar:${edge}:${s}`,
    tabs: () => (sections[s] ?? []).map((entry): TabRef => ({ key: entry.key, kind: 'widget', placement: entry.placement, source: store })),
    active: () => shown.find((entry) => entry.section === s)?.key ?? null,
    select: press,
    panel: () => (shown.length > 0 && look === 'held' ? 'open' : 'closed'),
    strip: 'keys',
    toolbar: 'corner',
    menuHost: 'bar-key',
    headerId: (tab) => railBodyKey(tab.placement!.cell, tab.placement!.target, tab.placement!.instance),
    openMenu: (tab, anchor) => {
      if (anchor instanceof HTMLElement) keyMenu = { key: tab.key, anchor };
    },
  }));
  const strip_zones = $derived(zones.slice(0, sections.length));
  const keyMark = $derived(drag.state.index !== null ? { section: aim.section, index: drag.state.index } : null);
  $effect(() => {
    if (!strip) return;
    const bar = strip;
    const win = bar.ownerDocument.defaultView ?? window;
    const root = bar.ownerDocument.documentElement;
    const name = horizontal ? '--oc-free-bottom' : '--oc-free-right';
    const publish = (): void => {
      const box = bar.getBoundingClientRect();
      const inset = horizontal ? win.innerHeight - box.top : win.innerWidth - box.left;
      root.style.setProperty(name, `${Math.max(0, Math.round(inset))}px`);
    };
    publish();
    const watch = new ResizeObserver(publish);
    watch.observe(bar);
    win.addEventListener('resize', publish);
    return () => {
      watch.disconnect();
      win.removeEventListener('resize', publish);
      root.style.removeProperty(name);
    };
  });

</script>

<svelte:window bind:innerWidth={winW} bind:innerHeight={winH} />
{#if present}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <nav class="rail" class:rail--bottom={horizontal} id={spec.id} bind:this={strip} data-session-rail data-rail-edge={edge}
    data-bar-size={size} data-bar-state={look}
    style={`${barVars(edge, size)}${flowed ? '' : `--rail-track:${HANDLE_PX}px;`}${pushPx > 0 ? ` ${horizontal ? 'margin-top' : 'margin-left'}: ${pushPx}px` : ''}` || undefined} data-rail-push={pushPx}
    data-editing={editing} data-drop={drop} data-rail-split-count={sections.length}
    aria-label={t(horizontal ? 'session_rail.label_bottom' : 'session_rail.label')}
    oncontextmenu={(event) => onRailContextMenu(event, edge)} onkeydown={(event) => onRailMenuKey(event, edge)}
    onpointerenter={visibility.onpointerenter} onpointerleave={visibility.onpointerleave}
    onfocusin={visibility.onfocusin} onfocusout={visibility.onfocusout}>
    {#if showsHandle(look)}
      <div class="rail__handle"><ZoneHandle {edge} expanded={barOut(look)} controls={spec.id} peek={visibility} drag={barDrag} /></div>
    {/if}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="rail__layer" data-rail-layer data-out={barOut(look)} inert={!barOut(look)} onkeydown={visibility.onkeydown}
      style={pinDrawn ? `--rail-pin-slot:${Math.min(BAR_SIZES[size][edge].keyW ?? 28, 28) + BAR_SIZES[size][edge].gap}px` : undefined}>
    {#if !editing && barOut(look)}
      <BarEdge {edge} label={t(horizontal ? 'widget_bars.bar_edge.bottom' : 'widget_bars.bar_edge.side')} place={barPlace} text={t(`widget_bars.size.${barPlace === 0 ? 'closed' : size}`)}
        onpress={(pos, extent) => barDrag.begin(pos, extent)} onkey={(key) => barDrag.key(key)} />
    {/if}
    {#if pinDrawn}
      <div class="rail__pin">
        {#if editing}
          <EditCell hidden={pinHidden} name={t('session_rail.pin_name')} ontoggle={() => void setRailIconHidden(pinId, !pinHidden)}><BarPin {edge} /></EditCell>
        {:else}
          <BarPin {edge} />
        {/if}
      </div>
    {/if}
    <ZoneKeys zones={strip_zones} axis={spec.axis} {cuts} {ghostAfter} ghostAimed={aim.onBox} {carriedKey} {labelAt} iconPx={BAR_SIZES[size][edge].icon} compact={size === 'compact'} {editing} {openKeys} {face} mark={keyMark} hiddenKey={railIconHidden} ontoggle={(key, hide) => void setRailIconHidden(key, hide)}
      empty={editing && drawnCount === 0 ? t(horizontal ? 'session_rail.empty_bottom' : 'session_rail.empty') : null}
      onpress={(_zone, key) => press(key)} {onedit} {motion} />
    </div>
    
    {#each keyMenu ? [keyMenu] : [] as open (open)}
      <RailKeyMenu {edge} itemKey={open.key} anchor={open.anchor} onClose={() => (keyMenu = null)} />
    {/each}
    {#if shown.length && look === 'held'}
      <RailSlideout entries={shown} zones={strip_zones} instant={railSlideout.restoring} sections={sections.length} {cuts} {edge}
        onratio={(index, next) => store.previewCut(index, next)} onratiosave={() => store.saveCuts()} onclose={close} />
    {/if}
  </nav>
{/if}

<style>
  @layer components {
    .rail {
      position: relative;
      flex: none;
      width: var(--rail-track, var(--rail-w, 36px));
      min-height: 0;
      min-width: 0;
    }

    .rail--bottom {
      width: auto;
      height: var(--rail-track, var(--rail-h));
    }

    .rail[data-editing='true']::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: var(--oc-z-sheet);
      border: var(--oc-border) dashed var(--oc-cyan);
      pointer-events: none;
    }

    .rail[data-drop] .rail__layer {
      background: color-mix(in oklab, var(--oc-cyan) 6%, var(--oc-ground-titlerow));
    }

    .rail[data-drop='aimed'] .rail__layer {
      background: color-mix(in oklab, var(--oc-cyan) 12%, var(--oc-ground-titlerow));
    }
  }
</style>
