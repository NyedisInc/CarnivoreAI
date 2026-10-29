<script lang="ts">
    import { t } from '../i18n/index.svelte';
  import { RAIL_HELP_LINKS, type RailItem } from '../../opscenter/shell/rail-items';
  import { closeDrawerAfterSwitch, handleMenuHotkey } from '../drawer-tabs/menu-hotkeys';
  import { railDestinations, menuLeadItems, menuSettings } from '../drawer-tabs/menu-rows';
  import { menuPageState } from '../menu-page/menu-page-shell.svelte';
  import { menuPage } from '../menu-page/menu-pages';
  import { motionReduced } from '../motion/motion';
  import { animationTypeOff } from '../motion/animation-types';
  import { activeFlyout, handleFlyoutEscape } from './flyout.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import type { KeyFace } from '../zone-shell/zone-types';
  import { FLYOUT_CONTAINER_ID } from './rail-dom';
  import { railKeyTarget } from './rail-keys.svelte';
  import { barPinned } from '../widget-bars/bar-pin-action';
  import type { Snippet } from 'svelte';

  let { pin }: { pin?: Snippet } = $props();

  const lead = $derived(menuLeadItems());
  const destinations = $derived(railDestinations());
  const settings = $derived(menuSettings());
  const items = $derived<RailItem[]>([...lead, ...destinations, ...RAIL_HELP_LINKS, ...(settings ? [settings] : [])]);
  const keyIds = $derived(items.map((i) => i.id));
  const leadIds = $derived(new Set(lead.map((i) => i.id)));
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
    return keyFace({ ariaLabel: nameOf(item), icon: item.icon, count: item.badge?.() ?? null });
  }

  function press(item: RailItem, event: MouseEvent): void {
    if (leadIds.has(item.id)) {
      item.run?.();
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

  const RADIUS_PX = 76;
  const PEAK = 0.5;
  let label = $state<HTMLElement | null>(null);
  let labelText = $state('');
  let labelOn = $state(false);
  let cells: { el: HTMLElement; y: number }[] = [];
  let frame = 0;
  let pointerY = 0;

  function measure(): void {
    cells = [...(nav?.querySelectorAll<HTMLElement>('[data-dock-name]') ?? [])].map((el) => {
      const r = el.getBoundingClientRect();
      return { el, y: r.top + r.height / 2 };
    });
  }

  function magnify(): void {
    frame = 0;
    for (const c of cells) {
      const d = Math.abs(pointerY - c.y);
      const k = d >= RADIUS_PX ? 0 : (Math.cos((Math.PI * d) / RADIUS_PX) + 1) / 2;
      c.el.style.setProperty('--dock-s', String(1 + PEAK * k));
    }
  }

  function onPointerMove(event: PointerEvent): void {
    if (event.pointerType === 'touch' || motionReduced() || animationTypeOff('transitions')) return;
    if (cells.length === 0) measure();
    pointerY = event.clientY;
    if (frame === 0) frame = requestAnimationFrame(magnify);
  }

  function rest(): void {
    if (frame !== 0) cancelAnimationFrame(frame);
    frame = 0;
    for (const c of cells) c.el.style.removeProperty('--dock-s');
    cells = [];
    labelOn = false;
  }

  function showLabel(cell: HTMLElement | null): void {
    if (!cell || !nav || !label) return;
    const resting = cells.find((c) => c.el === cell)?.y;
    const box = cell.getBoundingClientRect();
    const y = resting ?? box.top + box.height / 2;
    labelText = cell.dataset.dockName ?? '';
    label.style.transform = `translate(${nav.getBoundingClientRect().right + 8}px, ${y}px) translateY(-50%)`;
    labelOn = true;
  }

  const cellOf = (target: EventTarget | null): HTMLElement | null => (target as HTMLElement | null)?.closest<HTMLElement>('[data-dock-name]') ?? null;

  const pinLabel = $derived(t(barPinned('rail') ? 'sidebar.rail.menu.unpin' : 'sidebar.rail.menu.pin'));
</script>

{#snippet railButton(item: RailItem)}
  <span class="sbr-rail__cell" data-dock-name={t(item.labelKey)}>
    <TabKey
      id={item.id}
      variant="rail"
      face={faceOf(item)}
      iconPx={17}
      state={item.pressed ? 'pressed' : null}
      active={item.pressed?.() ?? false}
      tabbable={stop === item.id}
      attrs={{ 'data-rail-widget': item.widgetId, 'data-rail-key': item.id, 'aria-current': !leadIds.has(item.id) && activeRow === item.id ? 'page' : undefined }}
      close={item.close ? { label: t('drawer.tabs.close', { name: t(item.labelKey) }), run: () => item.close?.(), attrs: { 'data-rail-close': item.id } } : undefined}
      onfocus={() => (focused = item.id)}
      onpress={(_id, event) => press(item, event)}
    />
  </span>
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav
  class="sbr-rail"
  aria-label={t('sidebar.rail.label')}
  bind:this={nav}
  onkeydown={onKeydown}
  onpointerenter={measure}
  onpointermove={onPointerMove}
  onpointerleave={rest}
  onpointerover={(event) => showLabel(cellOf(event.target))}
  onfocusin={(event) => { if ((event.target as HTMLElement).matches(':focus-visible')) showLabel(cellOf(event.target)); }}
  onfocusout={() => (labelOn = false)}
>
  {#each lead as item (item.id)}{@render railButton(item)}{/each}
  <span class="sbr-rail__sep" aria-hidden="true"></span>
  {#each destinations as item (item.id)}{@render railButton(item)}{/each}
  <span class="sbr-rail__sep" aria-hidden="true"></span>
  {#each RAIL_HELP_LINKS as item (item.id)}{@render railButton(item)}{/each}
  <span class="sbr-rail__fill" aria-hidden="true"></span>
  {#if settings}{@render railButton(settings)}{/if}
  {#if pin}<span class="sbr-rail__cell" data-dock-name={pinLabel}>{@render pin()}</span>{/if}
</nav>
<span class="sbr-rail__label" class:sbr-rail__label--on={labelOn} aria-hidden="true" bind:this={label}><span class="sbr-rail__label-text">{labelText}</span></span>

<style>
  @layer components {
    .sbr-rail {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--oc-space-0-5);
      height: 100%;
      padding: var(--oc-space-2) 0;
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
      transform: scale(var(--dock-s, 1));
      transition: transform 90ms ease-out;
    }

    @media (min-width: 701px) {
      .sbr-rail__cell :global(.sbr-rail__btn) {
        width: 28px;
        height: 28px;
      }
    }

    .sbr-rail__sep {
      flex: none;
      width: 22px;
      height: var(--oc-border);
      margin: var(--oc-space-0-5) 0;
      background: var(--oc-line-rule);
    }

    .sbr-rail__fill {
      flex: 1 1 auto;
    }

    .sbr-rail__label {
      position: fixed;
      top: 0;
      left: 0;
      z-index: 4;
      pointer-events: none;
      opacity: 0;
      transition: opacity var(--oc-motion-fast) ease-out;
    }

    .sbr-rail__label--on {
      opacity: 1;
    }

    .sbr-rail__label-text {
      display: block;
      padding: var(--oc-space-1) 9px;
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-line-panel);
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      white-space: nowrap;
      transform: translateX(-6px);
      transition: transform var(--oc-motion-fast) ease-out;
    }

    .sbr-rail__label--on .sbr-rail__label-text {
      transform: translateX(0);
    }

    @media (prefers-reduced-motion: reduce) {
      .sbr-rail__cell,
      .sbr-rail__label,
      .sbr-rail__label-text {
        transition: none;
      }

      .sbr-rail__label-text {
        transform: none;
      }
    }
  }
</style>
