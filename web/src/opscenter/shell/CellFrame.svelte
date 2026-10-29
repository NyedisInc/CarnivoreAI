<script lang="ts">
  import { tick, untrack, type Snippet } from 'svelte';
  import IconButton from '../../lib/base/IconButton.svelte';
  import ArtFrame from '../art/ArtFrame.svelte';
  import CellMenu from '../engine/CellMenu.svelte';
  import WidgetHead from './WidgetHead.svelte';
  import CornerMenu from './CornerMenu.svelte';
  import { PHONE_HEAD_PX, type MenuSlot } from './widget-head';
  import { closeOffered, closeWidget } from '../engine/close-widget';
  import type { CellMeta, PhoneSummary, SlotId } from '../engine/types';
  import { kindOf } from '../engine/meta';
  import type { LayoutStore } from '../engine/layout.svelte';
  import { observeCell } from '../engine/observe.svelte';
  import { beginCellDrag } from '../engine/pointer';
  import { layoutZoom } from '../engine/layout-zoom.svelte';
  import { componentMerge } from '../engine/tab-drag';
  import { reducedMotion, viewport } from '../engine/viewport.svelte';
  import { inputFocus } from '../lib/input-focus.svelte';
  import ZoneShell from '../../lib/zone-shell/ZoneShell.svelte';
  import { createGridZone } from './grid-zone';
  import { layoutEditor } from '../layout-editor/editor.svelte';
  import FrameFitBody from '../widgets/chrome/FrameFitBody.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    meta,
    count = null,
    suffix = null,
    onRightControl,
    instance,
    widthState,
    heightState,
    collapsed = false,
    onToggleCollapse,
    summary = null,
    total = null,
    expanded = false,
    onToggleExpanded,
    store,
    body,
  }: {
    meta: CellMeta;
    /* could not determine */
    count?: number | null;
    suffix?: string | null;
    onRightControl?: () => void;
    instance: SlotId;
    widthState: string;
    heightState: string;
    collapsed?: boolean;
    onToggleCollapse?: () => void;
    summary?: PhoneSummary | null;
    total?: number | null;
    expanded?: boolean;
    onToggleExpanded?: () => void;
    store: LayoutStore;
    body: Snippet;
  } = $props();

  const zone = createGridZone(untrack(() => instance), () => (phoneShut ? 'collapsed' : 'open'));
  const tabKey = untrack(() => zone.tabs[0]!.key);
  const cellHeader = zone.headerFor(tabKey);
  const watchOnScreen = zone.watch(tabKey);

  const title = $derived(cellHeader.title || (kindOf(untrack(() => instance)) === 'analytics' ? '' : t(meta.titleKey)));
  const labelTitle = $derived(title || t(meta.titleKey));
  const titleShort = $derived(!cellHeader.title && meta.titleShortKey ? t(meta.titleShortKey) : '');

  const collapsible = $derived(meta.rightControl === 'collapse');
  const bodyId = $derived(`${instance}-body`);

  const focused = $derived(inputFocus.owner === instance);

  const terminal = $derived(kindOf(meta.id) === 'terminal');

  const selected = $derived(
    terminal && (focused || (inputFocus.owner === null && inputFocus.selected === instance)),
  );

  const phoneCollapsible = $derived(viewport.phone && meta.chrome === 'card');
  const phoneShut = $derived(phoneCollapsible && collapsed);

  const titleRowPx = $derived(phoneCollapsible ? PHONE_HEAD_PX : meta.titleHeight);

  const chromeOff = $derived(
    meta.chrome === 'card' && !meta.ownHead && !phoneCollapsible && !cellHeader.strip && !store.isHeaderShown(meta.id),
  );
  const headShown = $derived(meta.chrome === 'card');
  const titleRow = $derived(
    headShown && !(cellHeader.strip && cellHeader.rowless && !cellHeader.content && !cellHeader.action
      && cellHeader.groups.length === 0),
  );

  $effect.pre(() => {
    cellHeader.drawn = headShown;
    cellHeader.takesBars = headShown && !phoneCollapsible && !cellHeader.content;
  });

  const cap = $derived(meta.phoneCap ?? 0);
  const overflow = $derived(
    viewport.phone && cap > 0 && total !== null && total > cap ? total - cap : 0,
  );
  const showMore = $derived(overflow > 0 && !phoneShut);

  const frameRows = $derived(
    [
      meta.chrome === 'card' && cellHeader.strip ? '5px' : '',
      meta.chrome === 'card' && cellHeader.strip ? 'var(--oc-titlerow)' : '',
      titleRow ? 'var(--oc-titlerow)' : '',
      collapsible || viewport.phone ? 'minmax(0, auto)' : 'minmax(0, 1fr)',
      showMore ? 'auto' : '',
    ]
      .filter(Boolean)
      .join(' '),
  );


  let corner = $state<HTMLElement | null>(null);
  let frameEl = $state<HTMLElement | null>(null);
  const editing = $derived(layoutEditor.active && layoutEditor.page === store.page);
  let wrap = $state<HTMLElement | null>(null);
  let menuOpen = $state(false);

  const COLLAPSE = 240;

  function toggleCollapse(): void {
    const element = wrap;
    const from = element ? element.getBoundingClientRect().height : 0;
    onToggleCollapse?.();
    if (!element || phoneCollapsible || reducedMotion()) return;
    void tick().then(() => {
      const to = element.getBoundingClientRect().height;
      if (Math.abs(from - to) < 1) return;
      for (const running of element.getAnimations()) running.cancel();
      element.animate([{ height: `${from}px` }, { height: `${to}px` }], { duration: COLLAPSE, easing: 'ease' });
    });
  }

  /* there is nothing */
  function onGripDown(event: PointerEvent): void {
    if (!viewport.wide || menuOpen || layoutZoom.isZoomed(meta.id)) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest('button, input, select, textarea, a, [role=dialog], [popover]')) return;
    const merge = terminal && store.page === 'terminal' ? componentMerge(meta.id) : undefined;
    beginCellDrag(event.currentTarget as HTMLElement, event, meta.id, store, merge);
  }

  function onBareGripDown(event: PointerEvent): void {
    if (!viewport.wide || menuOpen || layoutZoom.isZoomed(meta.id)) return;
    beginCellDrag(event.currentTarget as HTMLElement, event, meta.id, store);
  }

  const onCloseWidget = $derived(
    closeOffered(meta, meta.id) ? (from: DOMRect) => closeWidget(store, meta.id, { editing, from }) : null,
  );

  function onStripIconClick(button: HTMLElement): void {
    if (menuOpen && corner === button) {
      menuOpen = false;
      return;
    }
    corner = button;
    menuOpen = true;
  }
</script>

<ZoneShell {zone} bare>
  {#snippet tab()}
    <section
      bind:this={frameEl}
      class="oc-frame"
      class:oc-frame-bare={meta.chrome === 'bare'}
      class:oc-frame-terminal={terminal}
      class:popup-focus={selected}
      class:popup-focus-turn={selected}
      class:popup-focus-ring={selected && meta.chrome === 'bare'}
      data-cell={meta.id}
      data-instance={instance}
      data-width-state={widthState}
      data-height-state={heightState}
      data-collapsed={collapsible && collapsed ? '' : undefined}
      data-oc-focus={focused ? '' : undefined}
      aria-current={focused ? 'true' : undefined}
      style:--oc-titlerow={`${titleRowPx}px`}
      style:grid-template-rows={frameRows}
      data-zone-pane={tabKey}
      data-zone-visible={zone.visibility(tabKey)}
      {@attach watchOnScreen}
    >
      {#if selected}
        
        <span class="pf-sheen" aria-hidden="true"></span>
      {/if}
      {#if focused}
        
        <span class="oc-visually-hidden">{t('opscenter.frame.input_focus')}</span>
      {/if}
      {#if meta.chrome === 'card' && cellHeader.strip}
        
        <div class="oc-frame-topgap" aria-hidden="true"></div>
        
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="oc-frame-strip" onpointerdown={onGripDown}
          oncontextmenu={(event) => {
            if (event.target !== event.currentTarget || menuOpen) return;
            const door = event.currentTarget.querySelector<HTMLElement>('[data-corner]');
            if (!door) return;
            event.preventDefault();
            onStripIconClick(door);
          }}>
          {@render cellHeader.strip({
            onIconClick: onStripIconClick,
            menuOpen,
            menuLabel: t('opscenter.frame.options', { title: labelTitle }),
          })}
          {#if cellHeader.tools}{@render cellHeader.tools()}{/if}
        </div>
        {#if menuOpen}
          <CellMenu id={meta.id} anchor={corner} onClose={() => (menuOpen = false)} {store} />
        {/if}
      {/if}
      {#snippet gridMenu(slot: MenuSlot)}
        <CellMenu id={meta.id} anchor={slot.anchor} onClose={slot.close} {store} />
      {/snippet}
      {#snippet rowCorner()}
        <CornerMenu {meta} title={labelTitle} {editing} place="row" phone={phoneCollapsible} menu={gridMenu} bind:open={menuOpen} bind:anchor={corner} />
      {/snippet}
      {#if titleRow}
        <WidgetHead
          {meta}
          header={cellHeader}
          {title}
          label={labelTitle}
          {titleShort}
          {count}
          {suffix}
          {collapsed}
          {summary}
          phone={phoneCollapsible}
          {bodyId}
          corner={cellHeader.strip ? null : rowCorner}
          bare={chromeOff}
          onClose={onCloseWidget}
          {onGripDown}
          onToggleCollapse={toggleCollapse}
          {onRightControl}
        />
      {:else if meta.chrome === 'bare'}
        <CornerMenu
          {meta}
          menu={gridMenu}
          title={labelTitle}
          {editing}
          place="bare"
          phone={viewport.phone}
          onGripDown={onBareGripDown}
          bind:open={menuOpen}
          bind:anchor={corner}
        />
      {/if}
      <ArtFrame />
      {#if collapsible && meta.chrome !== 'card'}
        
        <IconButton
          label={collapsed ? t('opscenter.frame.expand', { title: labelTitle }) : t('opscenter.frame.collapse', { title: labelTitle })}
          variant="quiet" icon={collapsed ? 'chevron-down' : 'chevron-up'} iconSize={15} data-frame-collapse=""
          aria-expanded={!collapsed} aria-controls={bodyId} onclick={toggleCollapse} />
      {/if}
      <div
        bind:this={wrap}
        class="oc-frame-collapsewrap"
        class:oc-frame-collapsible={collapsible}
        id={bodyId}
        hidden={phoneShut}
      >
        <div class="oc-frame-body" class:oc-frame-body-capped={expanded} {@attach observeCell(meta.id)}>
          
          <FrameFitBody {meta} {store} frame={frameEl} titleRowPx={headShown ? titleRowPx : 0} {body} />
        </div>
      </div>
      {#if showMore}
        
        <button
          type="button"
          class="oc-frame-more"
          aria-expanded={expanded}
          aria-controls={bodyId}
          onclick={onToggleExpanded}
        >
          {expanded
            ? t('opscenter.frame.show_less')
            : t('opscenter.frame.view_more', { count: overflow })}
        </button>
      {/if}
    </section>
  {/snippet}
</ZoneShell>

<style>
  @layer components {
    .oc-frame {
      position: relative;
      display: grid;
      grid-template-rows: var(--oc-titlerow) minmax(0, 1fr);
      min-width: 0;
      min-height: 0;
      border-radius: var(--oc-radius);
      overflow: hidden;
      container: oc-cell oc-head / inline-size;
    }

    .oc-frame:not(.popup-focus) {
      background: var(--oc-ground-panel);
      border: var(--oc-border) solid var(--oc-line-frame);
    }

    .oc-frame-terminal:not(.popup-focus) {
      border-color: color-mix(in srgb, var(--oc-orange) 40%, var(--oc-line-panel));
    }

    .oc-frame-terminal.oc-frame-bare:not(.popup-focus)::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 41;
      pointer-events: none;
      border-radius: inherit;
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--oc-orange) 40%, var(--oc-line-panel));
    }

    .oc-frame.oc-frame-bare {
      position: relative;
      grid-template-rows: minmax(0, 1fr);
      background: transparent;
      border: 0;
      border-radius: 0;
      overflow: visible;
    }

    .oc-frame[data-oc-focus]:not(.oc-frame-terminal)::before {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 40;
      box-sizing: border-box;
      border-radius: inherit;
      pointer-events: none;
      border: 1px solid var(--oc-focus-edge);
      box-shadow: inset 0 0 9px -4px var(--oc-focus-glow);
      opacity: 0.75;
      will-change: opacity;
      animation: oc-focus-breathe var(--oc-focus-breathe) ease-in-out infinite;
    }

    @keyframes oc-focus-breathe {
      0%, 100% { opacity: 0.65; }
      50% { opacity: 0.95; }
    }

    :global([data-oc-still]) .oc-frame[data-oc-focus]:not(.oc-frame-terminal)::before {
      animation-play-state: paused;
    }

    @media (prefers-reduced-motion: reduce) {
      .oc-frame[data-oc-focus]:not(.oc-frame-terminal)::before {
        animation: none;
        opacity: 0.85;
        will-change: auto;
      }
  }

    .oc-frame[data-oc-focus]:not(.oc-frame-terminal) {
      border-color: var(--oc-orange);
    }

    .oc-frame-strip {
      display: flex;
      align-items: stretch;
      gap: var(--oc-space-2);
      min-width: 0;
      padding: 0 var(--oc-widget-inset);
      touch-action: none;
      cursor: grab;
      background: var(--oc-ground-tab-inactive);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .oc-frame-topgap {
      background: var(--oc-ground-tab-inactive);
    }

    .oc-frame-collapsewrap {
      display: grid;
      grid-template-rows: minmax(0, 1fr);
      min-width: 0;
      min-height: 0;
    }

    .oc-frame-collapsible {
      grid-template-rows: minmax(0, auto);
      overflow: hidden;
    }

    .oc-frame-collapsewrap[hidden] {
      display: none;
    }

    :global([data-frame-collapse]) {
      --oc-ibtn-size: 24px;
      position: absolute;
      top: 10px;
      right: 16px;
      z-index: 3;
    }

    .oc-frame-body {
      min-width: 0;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      /* at the same time */
      contain: layout paint;
    }

    .oc-frame-more {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-height: var(--oc-tap);
      padding: 0 var(--oc-space-3);
      background: none;
      border: 0;
      box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      cursor: pointer;
    }

    .oc-frame-more:hover {
      color: var(--oc-text-primary);
    }

    @media (max-width: 1023px) {
      :global([data-frame-collapse]) {
        min-width: var(--oc-tap);
        min-height: var(--oc-tap);
        justify-content: center;
      }

      /* and the three */
      .oc-frame-body {
        min-height: 0;
      }

      .oc-frame-body-capped {
        max-height: 60dvh;
        overflow-y: auto;
      }
  }

    @media (max-width: 639px) {
      :global([data-frame-collapse]) {
        display: none;
      }
  }
  }

  .oc-frame-terminal.popup-focus {
    --pf-ground: var(--oc-ground-panel);
    --pf-edge-top: var(--oc-orange);
    --pf-edge-bottom: var(--oc-orange);
    --pf-glow: color-mix(in srgb, var(--oc-orange) 60%, transparent);
    border-width: var(--oc-border);
    box-shadow: 0 0 5px var(--pf-glow), inset 0 0 5px var(--pf-glow);
  }

  :global([data-oc-still]) .oc-frame.popup-focus-turn > :global(.pf-sheen)::before {
    animation-play-state: paused;
  }

  @layer components {
    :global(:root[data-motion="off"]) .oc-frame[data-oc-focus]:not(.oc-frame-terminal)::before {
      opacity: 0.85;
      will-change: auto;
    }
  }
</style>
