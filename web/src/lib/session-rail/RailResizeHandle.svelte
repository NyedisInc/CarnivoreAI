<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import type { RailEdge } from './rail-model';
  import { OUT_STEP_PX, OUT_DEFAULT_PX, outMinPx } from './rail-size';
  import { widgetBars } from '../widget-bars/bar-settings.svelte';
  import { panelPins } from '../widget-bars/panel-pins.svelte';
  import { railOutSizes, roomFor } from './rail-out-size.svelte';
  import { RAIL_SPECS } from './rail-model';
  import { sectionStyle } from './rail-sections';

  const CLICK_SLOP_PX = 4;

  let { edge, label, parts = [], cut = null, pinnable = true, onpin }: { edge: RailEdge; label: string; parts?: { section: number; pinned: boolean }[]; cut?: number | null; pinnable?: boolean; onpin?: (section: number) => void } = $props();

  const side = $derived(edge === 'side');
  const pinned = $derived(parts.some((part) => part.pinned));
  let focused = $state<number | null>(null);
  const keySection = $derived(parts.find((part) => part.section === focused)?.section ?? parts[0]?.section ?? 0);

  function sectionAt(event: PointerEvent): number {
    if (cut === null || parts.length < 2) return parts[0]?.section ?? 0;
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const length = side ? box.height : box.width;
    const fraction = length > 0 ? ((side ? event.clientY - box.top : event.clientX - box.left) / length) : 0;
    return fraction >= cut ? 1 : 0;
  }
  let winW = $state(typeof window === 'undefined' ? 1280 : window.innerWidth);
  let winH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
  const room = $derived(side ? winW : winH);
  const now = $derived(railOutSizes.shown(edge, room));
  const max = $derived(railOutSizes.max(edge, room));

  let drag: { start: number; from: number; id: number; moved: boolean; section: number } | null = null;

  function along(event: PointerEvent): number {
    return side ? event.clientX : event.clientY;
  }

  function onpointerdown(event: PointerEvent): void {
    if (event.button !== 0) return;
    drag = { start: along(event), from: railOutSizes.shown(edge, roomFor(edge)), id: event.pointerId, moved: false, section: sectionAt(event) };
    try {
      (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    } catch {
    }
    event.preventDefault();
  }

  function onpointermove(event: PointerEvent): void {
    if (!drag || event.pointerId !== drag.id) return;
    if (!drag.moved && Math.abs(along(event) - drag.start) < CLICK_SLOP_PX) return;
    drag.moved = true;
    railOutSizes.set(edge, drag.from + (drag.start - along(event)), roomFor(edge));
  }

  function onpointerup(event: PointerEvent): void {
    if (!drag || event.pointerId !== drag.id) return;
    const { moved, section } = drag;
    drag = null;
    focused = section;
    if (moved) railOutSizes.remember(edge);
    else onpin?.(section);
  }

  function onpointercancel(): void {
    if (!drag) return;
    const { moved } = drag;
    drag = null;
    if (moved) railOutSizes.remember(edge);
  }

  function onkeydown(event: KeyboardEvent): void {
    const grow = side ? 'ArrowLeft' : 'ArrowUp';
    const shrink = side ? 'ArrowRight' : 'ArrowDown';
    if (event.key === grow || event.key === shrink) {
      event.preventDefault();
      event.stopPropagation();
      railOutSizes.set(edge, now + (event.key === grow ? OUT_STEP_PX : -OUT_STEP_PX), roomFor(edge));
      railOutSizes.remember(edge);
    } else if (event.key === 'End') {
      event.preventDefault();
      event.stopPropagation();
      railOutSizes.set(edge, max, roomFor(edge));
      railOutSizes.remember(edge);
    } else if (event.key === 'Home') {
      event.preventDefault();
      event.stopPropagation();
      railOutSizes.set(edge, OUT_DEFAULT_PX[edge], roomFor(edge));
      railOutSizes.remember(edge);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopPropagation();
      onpin?.(keySection);
    }
  }
</script>

<svelte:window bind:innerWidth={winW} bind:innerHeight={winH} />

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="rail-grip"
  class:rail-grip--side={side}
  class:rail-grip--bottom={!side}
  role="separator"
  tabindex="0"
  aria-orientation={side ? 'vertical' : 'horizontal'}
  aria-label={label}
  aria-valuemin={outMinPx(edge, widgetBars.view[edge].size)}
  aria-valuemax={max}
  aria-valuenow={now}
  data-rail-grip={edge}
  {onpointerdown}
  {onpointermove}
  {onpointerup}
  {onpointercancel}
  onlostpointercapture={onpointercancel}
  title={!pinned && !pinnable ? t('widget_bars.pin_refused') : t('widget_bars.edge_keys')}
  {onkeydown}
><span class="rail-edge__line"></span><span class="rail-edge__pins">{#each parts as part (part.section)}{#if part.pinned}<span class="rail-edge__pin" data-rail-pin-section={part.section} style={sectionStyle(RAIL_SPECS[edge].axis, part.section, parts.length > 1 && cut !== null ? 2 : 1, cut ?? 0.5)}></span>{/if}{/each}</span></div>

<style>
  @layer components {
    .rail-grip {
      --edge-line: 2px;
      --edge-reach: 5px;
      --edge-hit: 8px;
      position: absolute;
      z-index: 2;
      touch-action: none;
      background: transparent;
      outline: none;
    }

    .rail-edge__line {
      position: absolute;
      background: var(--oc-line-frame);
      transition: background 120ms ease;
    }

    .rail-grip:hover .rail-edge__line,
    .rail-grip:focus-visible .rail-edge__line {
      background: var(--oc-text-dim);
    }

    .rail-edge__pin {
      position: absolute;
      background: var(--oc-orange);
    }

    .rail-edge__pins {
      position: absolute;
      pointer-events: none;
    }

    .rail-grip--side {
      top: 0;
      bottom: 0;
      left: calc(-1 * var(--edge-reach));
      width: var(--edge-hit);
      cursor: ew-resize;
    }

    .rail-grip--side .rail-edge__line {
      top: 0;
      bottom: 0;
      left: var(--edge-reach);
      width: var(--edge-line);
    }

    .rail-grip--side .rail-edge__pins {
      top: 0;
      bottom: 0;
      left: var(--edge-reach);
      width: var(--edge-line);
    }

    .rail-grip--bottom {
      left: 0;
      right: 0;
      top: calc(-1 * var(--edge-reach));
      height: var(--edge-hit);
      cursor: ns-resize;
    }

    .rail-grip--bottom .rail-edge__line {
      left: 0;
      right: 0;
      top: var(--edge-reach);
      height: var(--edge-line);
    }

    .rail-grip--bottom .rail-edge__pins {
      left: 0;
      right: 0;
      top: var(--edge-reach);
      height: var(--edge-line);
    }

    @media (prefers-reduced-motion: reduce) {
      .rail-edge__line {
        transition: none;
      }
    }
  }
</style>
