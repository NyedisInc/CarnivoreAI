<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { sessionSidebar, type SidebarPick } from '../legacy-globals';
  import MiniRailFooter from '../mini-rail/MiniRailFooter.svelte';
  import MiniRailUsage from '../mini-rail/MiniRailUsage.svelte';
  import { type RailItem } from '../../opscenter/shell/rail-items';
  import { closeDrawerAfterSwitch, handleMenuHotkey } from '../drawer-tabs/menu-hotkeys';
  import { menuLeadItems, railZoneItems, zoneEntries } from '../drawer-tabs/menu-rows';
  import { onMount, tick } from 'svelte';
  import { saveRailOrder, startMenuOrder } from '../drawer-tabs/menu-order.svelte';
  import { RAIL_SPLIT, zoneSequence } from './rail-zones';
  import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import EditCell from '../zone-shell/EditCell.svelte';
  import { menuDragActive, onMenuMoveKey, onMenuPointerDown, type MenuDragHost } from '../drawer-tabs/menu-drag';
  import { RAIL_PIN_ID, railIconHidden, railIconsShown, setRailIconHidden, startRailIcons } from './rail-icons.svelte';
  import { menuPageState } from '../menu-page/menu-page-shell.svelte';
  import { menuPage } from '../menu-page/menu-pages';
  import { activeFlyout, handleFlyoutEscape } from './flyout.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import type { KeyFace } from '../zone-shell/zone-types';
  import { FLYOUT_CONTAINER_ID } from './rail-dom';
  import { railKeyTarget } from './rail-keys.svelte';
  import { barPinned, railPinOffered } from '../widget-bars/bar-pin-action';
  import { QUESTIONS_FLYOUT } from './widget-ids';
  import { railDockNames, startRailDockNames } from './rail-dock-names.svelte';
  import type { Snippet } from 'svelte';

  let { pin, pinName, stats = false, pinHideable = true }: { pin?: Snippet; pinName?: string; stats?: boolean; pinHideable?: boolean } = $props();

  const editing = $derived(layoutEditor.active);
  const zones = $derived(railZoneItems());
  const top = $derived(railIconsShown(zones.top));
  const bottom = $derived(railIconsShown(zones.bottom));
  const items = $derived<RailItem[]>([...top, ...bottom]);
  onMount(() => {
    startRailIcons();
    const stopOrder = startMenuOrder();
    return stopOrder;
  });

  function refocusAfterPaint(id: string): void {
    void tick().then(() => focusKey(id));
  }

  const dragHost: MenuDragHost = {
    ids: () => zoneSequence({ top: zones.top.map((i) => i.id).filter((id) => id !== 'warroom'), bottom: zones.bottom.map((i) => i.id).filter((id) => id !== 'warroom') }),
    commit: (ids) => {
      saveRailOrder(ids);
      const moved = document.activeElement instanceof HTMLElement ? document.activeElement.closest<HTMLElement>('[data-rail-key]')?.dataset.railKey : undefined;
      if (moved) refocusAfterPaint(moved);
    },
    marker: RAIL_SPLIT,
  };
  const keyIds = $derived(items.map((i) => i.id));
  const leadIds = $derived(new Set(menuLeadItems().map((i) => i.id)));
  const activeRow = $derived(menuPageState.open ? (menuPage(menuPageState.open)?.railItem ?? null) : null);
  let nav = $state<HTMLElement | null>(null);
  let focused = $state<string | null>(null);
  const stop = $derived(focused !== null && keyIds.includes(focused) ? focused : (keyIds[0] ?? null));

  function nameOf(item: RailItem): string {
    const count = item.badge?.() ?? null;
    const name = t(item.labelKey);
    return count === null ? name : t('sidebar.rail.with_count', { name, count });
  }

  function faceOf(item: RailItem): KeyFace {
    return keyFace({ ariaLabel: nameOf(item), icon: item.icon });
  }

  function press(item: RailItem, event: MouseEvent): void {
    if (leadIds.has(item.id)) {
      item.run?.();
      if (item.pressed && document.body.classList.contains('session-sidebar-railed')) {
        sessionSidebar<SidebarPick<'open'>>()?.open();
      }
      if (activeFlyout() !== null && event.detail === 0) {
        queueMicrotask(() => document.querySelector<HTMLElement>(`#${FLYOUT_CONTAINER_ID} [data-flyout-close]`)?.focus());
      }
      return;
    }
    item.run?.();
    closeDrawerAfterSwitch();
  }

  function keyOf(event: KeyboardEvent): string | null {
    return (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-rail-key]')?.dataset.railKey ?? null;
  }

  function focusKey(id: string): void {
    nav?.querySelector<HTMLElement>(`[data-rail-key="${id}"]`)?.focus();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (handleFlyoutEscape(event, document.getElementById(FLYOUT_CONTAINER_ID))) return;
    const id = keyOf(event);
    if (id === null) return;
    if (editing && onMenuMoveKey(event, dragHost)) return;
    if (handleMenuHotkey(event)) return;
    const item = items.find((i) => i.id === id);
    if (event.key === 'Delete' && item?.close) {
      event.preventDefault();
      item.close();
      queueMicrotask(() => focusKey(keyIds[0] ?? ""));
      return;
    }
    const next = railKeyTarget(event.key, keyIds, id);
    if (next === null) return;
    event.preventDefault();
    focusKey(next);
  }

  let label = $state<HTMLElement | null>(null);
  let labelText = $state('');
  let labelIcon = $state('');
  let labelOn = $state(false);

  startRailDockNames();

  function showLabel(cell: HTMLElement | null): void {
    if (!cell || !nav || !label) return;
    if (editing || !railDockNames.on) {
      labelOn = false;
      return;
    }
    const box = cell.getBoundingClientRect();
    labelText = cell.dataset.dockName ?? '';
    labelIcon = cell.dataset.dockIcon ?? '';
    const at = label.getBoundingClientRect();
    const originX = at.left - (parseFloat(label.style.left) || 0);
    const originY = at.top - (parseFloat(label.style.top) || 0);
    label.style.left = `${(labelIcon ? box.left : Math.max(nav.getBoundingClientRect().right, box.right) + 6) - originX}px`;
    label.style.top = `${box.top - originY}px`;
    label.style.height = `${box.height}px`;
    labelOn = true;
  }

  const cellOf = (target: EventTarget | null): HTMLElement | null => (target as HTMLElement | null)?.closest<HTMLElement>('[data-dock-name]') ?? null;

  const pinLabel = $derived(pinName ?? t(barPinned('rail') ? 'sidebar.rail.menu.unpin' : 'sidebar.rail.menu.pin'));
</script>

{#snippet railKey(item: RailItem)}
  <TabKey
    id={item.id}
    variant="rail"
    face={faceOf(item)}
    iconPx={17}
    state={item.pressed ? 'pressed' : null}
    active={item.pressed?.() ?? false}
    tabbable={stop === item.id}
    attrs={{ 'data-rail-widget': item.widgetId, 'data-rail-attention': item.widgetId === QUESTIONS_FLYOUT ? 'question' : undefined, 'data-rail-key': item.id, 'aria-current': !leadIds.has(item.id) && activeRow === item.id ? 'page' : undefined }}
    close={item.close ? { label: t('drawer.tabs.close', { name: t(item.labelKey) }), run: () => item.close?.(), attrs: { 'data-rail-close': item.id } } : undefined}
    onfocus={() => (focused = item.id)}
    onpress={(_id, event) => press(item, event)}
  />
{/snippet}


{#snippet dockCell(name: string, body: Snippet, icon?: string)}
  <span class="sbr-rail__cell" data-dock-name={name} data-dock-icon={icon}>{@render body()}</span>
{/snippet}

{#snippet railButtonBody(item: RailItem)}
  <span class="oc-nav-label" hidden>{t(item.labelKey)}</span>
  {#if editing}
    <EditCell hidden={railIconHidden(item.id)} name={t(item.labelKey)} ontoggle={() => void setRailIconHidden(item.id, !railIconHidden(item.id))}>
      {@render railKey(item)}
    </EditCell>
  {:else}
    {@render railKey(item)}
  {/if}
{/snippet}

{#snippet railButton(item: RailItem)}
  {@render dockCell(t(item.labelKey), itemBody, item.icon)}
  {#snippet itemBody()}{@render railButtonBody(item)}{/snippet}
{/snippet}


{#snippet zone(name: string, list: RailItem[], end: string | undefined)}
  <ul class="sbr-rail__zone" data-menu-zone data-rail-zone={name} data-menu-end={end} data-empty={list.length === 0 ? '' : undefined}>
    {#each zoneEntries(list) as entry, i (entry.kind === 'row' ? entry.item.id : `${entry.kind}:${i}`)}
      {#if entry.kind === 'sep'}<li class="sbr-rail__sep" aria-hidden="true"></li>
      {:else if entry.kind === 'head'}<li class="sbr-rail__head" aria-hidden="true"></li>
      {:else}<li data-menu-row={entry.item.id}>{@render railButton(entry.item)}</li>{/if}
    {/each}
  </ul>
{/snippet}


{#snippet pinCell(body: Snippet)}
  {#if !pinHideable}
    {@render dockCell(pinLabel, body)}
  {:else if !railPinOffered()}
    
  {:else if editing}
    {@render dockCell(pinLabel, editedPin)}
  {:else if !railIconHidden(RAIL_PIN_ID)}
    {@render dockCell(pinLabel, body)}
  {/if}
  {#snippet editedPin()}
    <EditCell hidden={railIconHidden(RAIL_PIN_ID)} name={pinLabel} ontoggle={() => void setRailIconHidden(RAIL_PIN_ID, !railIconHidden(RAIL_PIN_ID))}>
      {@render body()}
    </EditCell>
  {/snippet}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav
  class="sbr-rail"
  aria-label={t(editing ? 'sidebar.rail.edit.label' : 'sidebar.rail.label')}
  data-editing={editing ? '' : undefined}
  bind:this={nav}
  data-menu-zones
  onpointerdowncapture={(event) => { if (editing) onMenuPointerDown(event, dragHost); }}
  onkeydown={onKeydown}
  onpointerleave={() => (labelOn = false)}
  onpointerover={(event) => { if (!menuDragActive()) showLabel(cellOf(event.target)); }}
  onfocusin={(event) => { if ((event.target as HTMLElement).matches(':focus-visible')) showLabel(cellOf(event.target)); }}
  onfocusout={() => (labelOn = false)}
>
  {@render zone('top', top, RAIL_SPLIT)}
  <span class="sbr-rail__fill" aria-hidden="true"></span>
  {@render zone('bottom', bottom, undefined)}
  {#if pin}{@render pinCell(pin)}{/if}
  {#if stats}
    <MiniRailFooter railed />
    <MiniRailUsage />
  {/if}
</nav>
<span class="sbr-rail__label" class:sbr-rail__label--on={labelOn} class:sbr-rail__label--bare={!labelIcon} aria-hidden="true" bind:this={label}>{#if labelIcon}<span class="sbr-rail__label-icon"><Icon name={labelIcon} size={17} /></span>{/if}<span class="sbr-rail__label-text">{labelText}</span></span>

<style>
  @layer components {
    .sbr-rail {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--sbr-row-gap);
      height: 100%;
      padding: var(--sbr-grid-top) 0 var(--sbr-rail-foot);
      box-sizing: border-box;
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-width: none;
      background: var(--oc-ground-chrome);
      box-shadow: inset calc(-1 * var(--oc-border)) 0 0 0 var(--oc-line-faint);
    }

    .sbr-rail::-webkit-scrollbar {
      display: none;
    }

    .sbr-rail__cell {
      position: relative;
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: var(--sidebar-rail-w);
      height: var(--sbr-row-h);
    }

    .sbr-rail__zone {
      display: flex;
      flex: none;
      flex-direction: column;
      align-items: center;
      gap: var(--sbr-row-gap);
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .sbr-rail__zone > li {
      display: flex;
      flex: none;
      width: var(--sidebar-rail-w);
      justify-content: center;
    }

    .sbr-rail[data-editing] .sbr-rail__zone[data-empty] {
      width: var(--oc-rail-key);
      min-height: var(--oc-rail-key);
      border: var(--oc-border) dashed var(--oc-cyan);
      border-radius: var(--oc-radius-sm);
      box-sizing: border-box;
    }

    .sbr-rail[data-editing] .sbr-rail__zone > li[data-menu-row] {
      cursor: grab;
      touch-action: none;
    }


    .sbr-rail__sep {
      align-items: center;
      height: var(--sbr-sep-h);
    }

    .sbr-rail__sep::before {
      content: '';
      width: 22px;
      height: var(--oc-border);
      background: var(--oc-line-rule);
    }

    .sbr-rail__head {
      height: var(--sbr-head-h);
    }

    .sbr-rail__fill {
      flex: 1 1 auto;
    }

    .sbr-rail__label {
      position: fixed;
      top: 0;
      left: 0;
      z-index: 4;
      display: flex;
      align-items: center;
      gap: calc(var(--oc-space-4) + var(--oc-space-1));
      box-sizing: border-box;
      padding: 0 var(--oc-space-3) 0 calc((var(--sidebar-rail-w) - 17px) / 2 - var(--oc-border));
      border: var(--oc-border) solid var(--oc-line-rule);
      border-radius: var(--oc-radius);
      background: var(--oc-ground-hover);
      box-shadow: 0 6px 14px -4px var(--oc-shadow-lift);
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-nav);
      white-space: nowrap;
      pointer-events: none;
      visibility: hidden;
      clip-path: inset(-20px calc(100% - var(--sidebar-rail-w)) -20px -20px);
    }

    .sbr-rail__label--bare {
      padding-left: var(--oc-space-3);
      clip-path: inset(-20px 100% -20px -20px);
    }

    .sbr-rail__label--on {
      visibility: visible;
      clip-path: inset(-20px -20px -20px -20px);
      transition: clip-path calc(var(--oc-motion-fast) / 2) cubic-bezier(0.2, 0.9, 0.3, 1);
    }

    .sbr-rail__label-icon {
      display: inline-flex;
      flex: 0 0 auto;
      color: var(--oc-orange);
    }

    .sbr-rail__label-text {
      text-transform: capitalize;
    }

    @media (prefers-reduced-motion: reduce) {
      .sbr-rail__label--on {
        transition: none;
      }
    }
  }
</style>
