<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import GripPill, { CLICK_SLOP_PX } from '../grip/GripPill.svelte';
  import { t } from '../i18n/index.svelte';
  import { DRAWER_LEDGER_ID } from '../drawer-tabs/drawer-tabs';
  import { GLANCE_ROW_HEIGHT_PX } from '../drawer-zone/glance';
  import { sidebarTabs } from './tab-store.svelte';
  import { snapAreaState, stepAreaState, widgetArea } from './widget-area.svelte';
  import type { WidgetAreaState } from './types';

  interface Props {
    state?: WidgetAreaState;
    onchange?: (next: WidgetAreaState) => void;
    area?: () => HTMLElement | null;
  }

  const { state: given, onchange, area: findArea }: Props = $props();

  const FULL_GUESS_PX = GLANCE_ROW_HEIGHT_PX * 4;

  const tabId = $derived(sidebarTabs.active());
  const areaState = $derived(given ?? widgetArea.stateFor(tabId));

  function setState(tab: string, next: WidgetAreaState): void {
    if (onchange) onchange(next);
    else widgetArea.set(tab, next);
  }

  const fullSeen: Record<string, number> = {};
  let dragged = false;

  const area = (): HTMLElement | null => (findArea ? findArea() : document.getElementById(DRAWER_LEDGER_ID));

  $effect(() => {
    const el = area();
    if (!el) return;
    el.dataset.areaState = areaState;
    if (findArea) return;
    el.style.height = '';
    el.style.maxHeight = '';
  });

  function noteFull(tab: string, el: HTMLElement): void {
    const h = el.getBoundingClientRect().height;
    if (h > 0) fullSeen[tab] = h;
  }

  function onClick(): void {
    if (dragged) {
      dragged = false;
      return;
    }
    if (areaState === 'closed') setState(tabId, 'full');
  }

  function onKeydown(event: KeyboardEvent): void {
    let next = null;
    if (event.key === 'ArrowUp') next = stepAreaState(areaState, 1);
    else if (event.key === 'ArrowDown') next = stepAreaState(areaState, -1);
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setState(tabId, areaState === 'full' ? 'closed' : 'full');
      return;
    }
    if (!next) return;
    event.preventDefault();
    setState(tabId, next);
  }

  function onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return;
    const bar = event.currentTarget as HTMLElement;
    const el = area();
    if (!el) return;
    event.preventDefault();
    dragged = false;
    const tab = tabId;
    if (areaState === 'full') noteFull(tab, el);
    const startY = event.clientY;
    const startH = areaState === 'closed' ? 0 : el.getBoundingClientRect().height;
    bar.setPointerCapture?.(event.pointerId);
    const move = (e: PointerEvent): void => {
      const dy = startY - e.clientY;
      if (!dragged && Math.abs(dy) < CLICK_SLOP_PX) return;
      dragged = true;
      const was = given ?? widgetArea.stateFor(tab);
      const next = snapAreaState(startH + dy, GLANCE_ROW_HEIGHT_PX, fullSeen[tab] ?? FULL_GUESS_PX);
      if (was === 'full' && next !== 'full') noteFull(tab, el);
      setState(tab, next);
    };
    const up = (): void => {
      bar.removeEventListener('pointermove', move);
      bar.removeEventListener('pointerup', up);
      bar.removeEventListener('pointercancel', up);
    };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', up);
    bar.addEventListener('pointercancel', up);
  }

  const stateLabel = $derived(t(`drawer.area.state.${areaState}`));
</script>

<div
  class="wab"
  role="separator"
  aria-orientation="horizontal"
  aria-label={t(areaState === 'closed' ? 'drawer.area.pull_up' : 'drawer.area.resize')}
  aria-valuetext={stateLabel}
  title={areaState === 'closed' ? t('drawer.area.pull_up') : undefined}
  tabindex="0"
  data-area-bar
  data-area-state={areaState}
  onpointerdown={onPointerDown}
  onclick={onClick}
  onkeydown={onKeydown}
>
  {#if areaState === 'closed'}
    <span class="wab-chevron" data-area-chevron aria-hidden="true"><Icon name="chevron-up" size={10} /></span>
    <span class="wab-hint" data-area-hint>{t('drawer.area.tap_to_enlarge')}</span>
  {:else}
    <GripPill axis="x" data-area-handle aria-hidden="true" />
  {/if}
</div>

<style>
  @layer components {
    .wab {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 10px;
      box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
      cursor: ns-resize;
      touch-action: none;
      user-select: none;
      color: var(--oc-text-dim);
    }

    .wab[data-area-state='closed'] {
      cursor: pointer;
    }

    .wab-chevron {
      display: inline-flex;
      line-height: 0;
    }

    .wab-hint {
      display: none;
    }

    @media (max-width: 1023px) {
      .wab[data-area-state='closed'] {
        min-height: var(--oc-tap, 44px);
        gap: var(--oc-space-2);
      }

      .wab[data-area-state='closed'] .wab-hint {
        display: inline;
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        letter-spacing: 0.04em;
      }
    }

    .wab:hover,
    .wab:focus-visible {
      --grip-color: var(--oc-text-dim);
    }

    .wab:hover,
    .wab:focus-visible {
      outline: none;
      color: var(--oc-text-secondary);
    }

    .wab:focus-visible {
      box-shadow: inset 0 1px 0 0 var(--oc-line-panel);
    }

    :global(.session-sidebar-ledger[data-area-state='closed']) {
      display: none;
    }

    :global(.session-sidebar-ledger[data-area-state='glance']) {
      height: auto;
      max-height: none;
      overflow: hidden;
    }

    :global(.session-sidebar-ledger[data-area-state='full']) {
      height: auto;
    }
  }
</style>
