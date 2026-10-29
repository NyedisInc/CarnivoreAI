<script lang="ts">
  /*  hidden  padding */
  import { untrack, type Snippet } from 'svelte';
  import { observeCell, sizeOf } from '../../opscenter/engine/observe.svelte';
  import { entryFor } from '../../opscenter/cells/registry';
  import { META, metaFor } from '../../opscenter/engine/meta';
  import type { SlotId } from '../../opscenter/engine/types';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import { placementHead, placementOptionsFor, type PlacementOptionValue, type PlacementOptions } from '../../opscenter/widgets/placement-options';
  import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
  import { checkFit } from '../../opscenter/widgets/fits';
  import { isNoShow } from '../../opscenter/widgets/no-show';
  import NoShowPlate from '../../opscenter/widgets/chrome/NoShowPlate.svelte';
  import RefusalPlate from '../../opscenter/widgets/chrome/RefusalPlate.svelte';
  import SettingsOverlay from '../../opscenter/widgets/chrome/SettingsOverlay.svelte';
  import { closeConfigure, configureSheet, isConfigurable, openConfigure } from '../../opscenter/widgets/chrome/configure.svelte';
  import { settingsPanelFor } from '../../opscenter/widgets/chrome/settings-panels.svelte';
  import { reportWidget } from '../../opscenter/widgets/chrome/report';
  import { activeScopeFor } from '../../opscenter/widgets/active-scope';
  import type { SessionScope } from '../../opscenter/widgets/session-scope';
  import PlacementHead from '../../opscenter/shell/PlacementHead.svelte';
  import { provideFrameHeader, provideTitlelessHost, type FrameHeader } from '../../opscenter/shell/frame-header.svelte';
  import { viewport } from '../../opscenter/engine/viewport.svelte';
  import { HEADER_OPTION, placementHeaderShown, type MenuSlot } from '../../opscenter/shell/widget-head';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';
  import { t } from '../i18n/index.svelte';
  import { panelPins } from '../widget-bars/panel-pins.svelte';
  import { pinnedAgent, pinnedScopeFor } from '../widget-bars/pinned-scope';
  import { CORE_ID } from '../widget-menu/model';
  import PlacementMenuHost from './PlacementMenuHost.svelte';
  import RailKeyMenu from '../widget-menu/RailKeyMenu.svelte';
  import { noteDrawn } from '../widget-menu/closed-key.svelte';
  import type { RailEdge } from '../session-rail/rail-model';
  import { HOST_LOOKS, type BodyHost } from './host-looks';
  import type { PlacementSource } from './source';
  import { useZonePane } from './zone-pane';
  import { isMenuKey } from './key-nav';

  let {
    host,
    manifest: widget,
    target = null,
    view = null,
    instance: copy = null,
    options = undefined,
    placementKey = '',
    source = null,
    pinRowId = null,
    scope = undefined,
    edge = 'side',
    unseen = false,
    head = undefined,
  }: {
    host: BodyHost;
    manifest: WidgetManifest;
    target?: string | null;
    view?: string | null;
    instance?: string | null;
    options?: PlacementOptions;
    placementKey?: string;
    source?: PlacementSource | null;
    pinRowId?: number | null;
    scope?: SessionScope | null;
    edge?: RailEdge;
    unseen?: boolean;
    head?: Snippet<[FrameHeader]>;
  } = $props();

  const look = $derived(HOST_LOOKS[host]);
  const rail = $derived(host === 'rail');
  const popout = $derived(host === 'popout');

  const resolved = $derived(resolvePlacement({ widget, view, target, instance: copy }));
  const manifest = $derived(resolved?.cell ?? widget);
  const slot = $derived((resolved?.slot ?? widget.id.slice('core.'.length)) as SlotId);
  const family = $derived(manifest.instancing !== 'singleton');
  const entry = $derived(entryFor(slot));
  const meta = $derived(family ? metaFor(slot, META) : META[slot as keyof typeof META]);
  const key = $derived(look.keyFor(manifest, target, copy));
  const box = $derived(sizeOf(key));
  const Cell = $derived(entry?.component);

  let localOptions = $state<PlacementOptions | null>(null);
  const shownOptions = $derived(localOptions ?? options);
  const count = $derived(rail ? (entry?.countFor ? entry.countFor(shownOptions) : null) : null);

  const noShow = $derived(look.fitPlates && isNoShow(manifest.fits, box.width > 0 ? box : null));
  const fit = $derived(look.fitPlates ? checkFit(manifest.fits, box.width > 0 ? box : null) : null);

  const scoped = $derived(pinRowId != null ? pinnedScopeFor(manifest, pinRowId) : scope !== undefined ? scope : activeScopeFor(manifest));
  const held = $derived(pinRowId != null && manifest.scope === 'session' && pinnedAgent(pinRowId).scope === null);
  $effect(() => (!unseen && pinRowId != null && widget.id === 'core.files' ? panelPins.holdFiles() : undefined));
  $effect(() => (!unseen ? noteDrawn(key) : undefined));

  const zoneHeader = untrack(() => (unseen ? undefined : useZonePane()?.header));
  const cellHeader = zoneHeader ?? untrack(() => provideFrameHeader(key));
  const surface = $derived(look.surface);
  const headShown = $derived(
    surface === 'rail'
      ? !!placementKey && placementHeaderShown('rail', shownOptions, widget.id)
      : surface === 'drawer'
        ? !!meta?.ownHead || placementHeaderShown('drawer', shownOptions)
        : true,
  );
  $effect.pre(() => {
    cellHeader.drawn = headShown;
    cellHeader.suppressed = !!surface && !headShown;
    cellHeader.takesBars = headShown && (popout || !viewport.phone) && !cellHeader.content;
  });
  const headDecl = $derived(placementHead(widget.id, shownOptions));
  const title = $derived(cellHeader.title || headDecl?.title || t(widget.titleKey));

  function writeOption(option: string, value: boolean | number | string): void {
    if (source) source.setOption(placementKey, option, value as PlacementOptionValue);
    else localOptions = { ...(shownOptions ?? {}), [option]: value } as PlacementOptions;
  }

  function remove(): void {
    if (source?.remove(placementKey) && look.announceRemoved) terminalLayout.announce(t('session_rail.announce.removed', { title }));
  }

  const declared = $derived(placementOptionsFor(widget.id) ?? null);

  let card = $state<HTMLElement | null>(null);
  const hasSchema = $derived(!!manifest.settings && Object.keys(manifest.settings.fields).length > 0);
  const configurable = $derived(look.card && isConfigurable(slot));
  const settingsOpen = $derived(look.card && configureSheet.slot === key && configureSheet.kind === 'settings');
  const panel = $derived(settingsOpen ? settingsPanelFor(slot) : null);

  const ownMenu = $derived(rail && declared?.menuHeadingKey !== undefined);
  const headless = $derived(!!surface && !headShown && !!placementKey);
  const menuOnBody = $derived(!popout && !!placementKey && (ownMenu || headless));
  let menuAt = $state<{ x: number; y: number } | null>(null);
  let menuSpot = $state<HTMLElement | null>(null);
  let bodyEl = $state<HTMLElement | null>(null);
  let menuByKey = false;

  function onContextMenu(event: MouseEvent): void {
    if (!menuOnBody || event.defaultPrevented || (event.target as Element | null)?.closest('input, textarea, [contenteditable]')) return;
    event.preventDefault();
    menuByKey = false;
    menuAt = { x: event.clientX, y: event.clientY };
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (!isMenuKey(event) || !menuOnBody || event.defaultPrevented) return;
    event.preventDefault();
    const at = ((event.target as Element | null) ?? bodyEl)?.getBoundingClientRect();
    menuByKey = true;
    menuAt = at ? { x: at.left, y: at.bottom } : { x: 0, y: 0 };
  }

  function closeMenu(): void {
    menuAt = null;
    if (menuByKey) bodyEl?.focus();
  }

  if (untrack(() => host) === 'rail') provideTitlelessHost();
</script>

{#snippet copyMenu(slot: MenuSlot)}
  {#if rail && source && placementKey}
    
    <RailKeyMenu {edge} itemKey={placementKey} anchor={slot.anchor} onClose={slot.close} />
  {:else}
    <PlacementMenuHost
      host="drawer-card"
      bodyHost={host}
      manifest={widget}
      {view}
      {target}
      instance={copy}
      options={shownOptions}
      {placementKey}
      {source}
      extras={{
        header: meta?.ownHead ? null : { shown: headShown, toggle: () => source?.setOption(placementKey, HEADER_OPTION, !headShown) },
        close: meta?.closable === false ? null : { run: remove },
        ...(configurable ? { settings: [[{ id: CORE_ID.settings, label: t('widgets.menu.settings'), icon: 'settings', run: () => openConfigure(key as SlotId) }]] } : {}),
      }}
      anchor={slot.anchor}
      label={t('opscenter.frame.options', { title })}
      onClose={slot.close}
    />
  {/if}
{/snippet}

{#snippet headRow()}
  {#if surface && meta && headShown}
    <PlacementHead
      {meta}
      header={cellHeader}
      {title}
      {count}
      icon={surface === 'drawer' ? (headDecl?.icon ?? widget.icon) : (headDecl?.icon ?? null)}
      shown={headShown}
      phone={viewport.phone}
      onRemove={meta.closable === false ? null : remove}
      menu={copyMenu}
    />
  {/if}
{/snippet}

{#snippet bodyRow()}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class={popout ? 'pb-body sw-body' : rail || host === 'tab' ? 'pb-body rail-body' : 'pb-body dzc-body'}
    data-rail-body={rail ? manifest.id : undefined}
    style={look.height ? `height: ${look.height}px` : undefined}
    {@attach observeCell(key)}
    bind:this={bodyEl}
    tabindex={headless && menuOnBody ? 0 : undefined}
    data-headless={headless ? '' : undefined}
    oncontextmenu={onContextMenu}
    onkeydown={onKeyDown}
  >
    {#if noShow}
      <NoShowPlate icon={widget.icon} widget={manifest.id} title={t(widget.titleKey)} />
    {:else if fit && !fit.ok}
      <RefusalPlate
        check={fit}
        sizes={manifest.fits.sizes}
        onReport={() => reportWidget({ widget: manifest.id, zone: look.zone, size: fit.has, reason: fit.reason })}
      />
    {:else if held}
      
    {:else if Cell && meta}
      <Cell
        width={box.width}
        height={box.height}
        {meta}
        instance={family ? slot : key}
        phone={false}
        limit={null}
        page={look.page}
        scope={scoped}
        options={shownOptions}
        onOption={popout || placementKey ? writeOption : undefined}
      />
    {/if}
  </div>
{/snippet}

{#if look.card}
  <section class="dzc" bind:this={card} data-zone-cell={manifest.id} data-zone-target={target ?? undefined} aria-label={title}>
    {@render headRow()}
    {@render bodyRow()}
  </section>
  {#if settingsOpen && declared && source}
    <SettingsOverlay
      widgetId={manifest.id}
      title={t(manifest.titleKey)}
      anchor={card}
      hasSchema={false}
      placement={{
        schema: declared.schema(),
        values: shownOptions ?? {},
        onChange: (option, value) => source.setOption(placementKey, option, value),
        onReset: () => source.resetOptions(placementKey),
        onClose: closeConfigure,
      }}
    />
  {:else if settingsOpen && (hasSchema || panel)}
    <SettingsOverlay widgetId={manifest.id} title={t(manifest.titleKey)} anchor={card} {hasSchema} {panel} />
  {/if}
{:else if popout}
  <section class="sw" data-popout-widget={widget.id} aria-label={title}>
    {@render head?.(cellHeader)}
    {@render bodyRow()}
  </section>
{:else}
  {@render headRow()}
  {@render bodyRow()}
{/if}
{#if menuAt}
  <span class="pb-menu-spot" bind:this={menuSpot} style:left={`${menuAt.x}px`} style:top={`${menuAt.y}px`} aria-hidden="true"></span>
  {@render copyMenu({ anchor: menuSpot, close: closeMenu })}
{/if}

<style>
  @layer components {
    .pb-menu-spot {
      position: fixed;
      width: 0;
      height: 0;
      pointer-events: none;
    }

    .pb-body {
      min-width: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }

    /* padding */
    .pb-body[data-headless] {
      box-sizing: border-box;
      border: var(--oc-border) solid transparent;
      margin: calc(-1 * var(--oc-border));
    }

    .rail-body {
      flex: 1 1 auto;
      min-height: 0;
    }

    /* the settings overlay */
    .dzc {
      position: relative;
      margin: 6px var(--oc-space-2) var(--oc-space-2);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      min-width: 0;
      container: oc-head / inline-size;
    }

    .sw {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      container: oc-head / inline-size;
    }

    .sw-body {
      flex: 1 1 auto;
      min-height: 0;
    }
  }
</style>
